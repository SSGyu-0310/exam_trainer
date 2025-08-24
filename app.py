import os
import random
import json
import sqlite3
from contextlib import closing
from flask import Flask, render_template, request, redirect, url_for, session, flash

# --- 앱 설정 ---
app = Flask(__name__)
app.secret_key = "change-me-for-production"  # 세션용 (개발 테스트 용도)

# --- 경로 및 DB 설정 ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "my_database.db")

# --- 데이터베이스 헬퍼 함수 ---
def get_db():
    """데이터베이스 커넥션을 반환합니다."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def get_structured_topics():
    """과목별로 주제를 묶어서 계층적인 딕셔너리 형태로 반환합니다."""
    structured_data = {}
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT subject FROM Question ORDER BY subject")
        subjects = [r["subject"] for r in cur.fetchall()]

        for subject in subjects:
            cur.execute("SELECT DISTINCT topic FROM Question WHERE subject = ? ORDER BY topic", (subject,))
            topics = [r["topic"] for r in cur.fetchall()]
            structured_data[subject] = topics
    return structured_data

# --- 시험 관련 라우트 ---
@app.route("/", methods=["GET", "POST"])
def index():
    """메인 페이지, 시험 설정."""
    structured_topics = get_structured_topics()
    
    question_counts_by_topic = {}
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute("SELECT topic, COUNT(*) as count FROM Question GROUP BY topic")
        rows = cur.fetchall()
        for row in rows:
            key = row['topic'] if row['topic'] is not None else '기타' 
            question_counts_by_topic[key] = row['count']

    question_counts_json = json.dumps(question_counts_by_topic)

    if request.method == "POST":
        selected_topics = request.form.getlist("topics")
        num_q = int(request.form.get("num_questions") or 5)
        
        session["filters"] = {"topics": selected_topics, "num_q": num_q}
        return redirect(url_for("start_exam"))

    return render_template("index.html", 
                           structured_topics=structured_topics, 
                           question_counts_json=question_counts_json)

@app.route("/start")
def start_exam():
    """시험 시작 페이지."""
    filters = session.get("filters", {"topics": [], "num_q": 5})
    topics = filters.get("topics", [])
    num_q = int(filters.get("num_q", 5))

    query = "SELECT * FROM Question"
    params = []
    if topics:
        placeholders = ",".join(["?"] * len(topics))
        query += f" WHERE topic IN ({placeholders})"
        params.extend(topics)

    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(num_q)

    questions_with_choices = []
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute(query, params)
        questions = cur.fetchall()

        for q in questions:
            choices_cur = con.cursor()
            choices_cur.execute("SELECT * FROM Choice WHERE question_id = ?", (q["question_id"],))
            choices = choices_cur.fetchall()

            # ✨[추가] 이 문제의 정답이 총 몇 개인지 계산합니다.
            correct_answer_count = sum(1 for c in choices if c["is_correct"])

            questions_with_choices.append({
                "question": q,
                "choices": choices,
                "correct_answer_count": correct_answer_count # ✨계산된 정답 개수를 함께 전달
            })

    session["current_exam"] = [q_wc["question"]["question_id"] for q_wc in questions_with_choices]
    return render_template("exam.html", questions_data=questions_with_choices)

@app.route("/submit", methods=["POST"])
def submit_exam():
    """시험 제출, 채점, 그리고 DB에 결과 기록."""
    qids = session.get("current_exam", [])
    if not qids:
        # 세션에 시험 정보가 없으면 메인으로 리디렉션
        return redirect(url_for("index"))

    user_answers = {}
    for qid in qids:
        key = f"q_{qid}"
        # 여러 답을 선택하는 경우를 대비해 getlist 사용
        user_answers[qid] = [int(val) for val in request.form.getlist(key)]

    results = []
    score = 0

    with closing(get_db()) as con:
        # 1. 문제 채점 및 결과 데이터 생성
        for qid in qids:
            cur = con.cursor()
            cur.execute("SELECT * FROM Question WHERE question_id = ?", (qid,))
            question_row = cur.fetchone()

            cur.execute("SELECT * FROM Choice WHERE question_id = ?", (qid,))
            choices = cur.fetchall()

            correct_choice_ids = [c["choice_id"] for c in choices if c["is_correct"]]
            chosen_choice_ids = user_answers.get(qid, [])
            
            # 정답 여부 확인 (선택한 답안 리스트와 정답 리스트가 완전히 일치하는지)
            is_correct = set(chosen_choice_ids) == set(correct_choice_ids)
            
            if is_correct:
                score += 1
            else:
                # 틀린 문제 ID를 WrongAnswer 테이블에 기록 (복습 기능용)
                check_cur = con.cursor()
                check_cur.execute("SELECT * FROM WrongAnswer WHERE question_id = ?", (qid,))
                if not check_cur.fetchone():
                    con.execute("INSERT INTO WrongAnswer (question_id) VALUES (?)", (qid,))
                    con.commit()

            # 메타인지(자신감) 값 가져오기
            confidence_value = request.form.get(f"confidence_q_{qid}", -1, type=int)
            
            # AnswerLog에 개별 문제 결과 기록
            con.execute(
                "INSERT INTO AnswerLog (question_id, is_correct, confidence) VALUES (?, ?, ?)",
                (qid, is_correct, confidence_value)
            )
            con.commit()

            # 결과 페이지에 보여줄 데이터 추가
            results.append({
                "question": question_row,
                "choices": choices,
                "chosen": chosen_choice_ids,
                "correct": correct_choice_ids,
                "is_correct": is_correct,
                "confidence": confidence_value
            })

        # 2. 시험 전체 결과(세션) DB에 저장
        total = len(qids)
        percent = int(round(score * 100.0 / total)) if total else 0

        session_cur = con.cursor()
        session_cur.execute(
            "INSERT INTO TestSession (score, total, percent) VALUES (?, ?, ?)",
            (score, total, percent)
        )
        session_id = session_cur.lastrowid # 방금 저장된 시험 세션의 ID
        con.commit()

        # 3. 각 문항별 사용자 답변을 UserAnswer 테이블에 저장
        answer_cur = con.cursor()
        for r in results:
            qid = r["question"]["question_id"]
            chosen_ids_json = json.dumps(r["chosen"]) # 선택 답안 ID 리스트를 JSON 문자열로 변환
            
            answer_cur.execute(
                """
                INSERT INTO UserAnswer (session_id, question_id, chosen_choice_ids, is_correct, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, qid, chosen_ids_json, r["is_correct"], r["confidence"])
            )
        con.commit()

    # 결과 페이지에서 '시험 기록 보기'로 바로 갈 수 있도록 session_id 전달
    return render_template(
        "results.html", 
        results=results, 
        score=score, 
        total=total, 
        percent=percent,
        session_id=session_id
    )

# --- 문제 관리용 라우트 ---
@app.route("/manage")
def manage():
    """문제 관리 페이지 (검색, 주제, 태그 필터 및 우선순위 정렬)."""
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '', type=str)
    selected_topic = request.args.get('topic', '', type=str)
    selected_tag = request.args.get('tag', '', type=str)

    PER_PAGE = 10
    offset = (page - 1) * PER_PAGE

    with closing(get_db()) as con:
        cur = con.cursor()

        # 필터링 UI를 위한 전체 주제 및 태그 목록 조회
        cur.execute("SELECT DISTINCT topic FROM Question WHERE topic IS NOT NULL AND topic != '' ORDER BY topic")
        all_topics = [row['topic'] for row in cur.fetchall()]
        
        cur.execute("SELECT DISTINCT tags FROM Question WHERE tags IS NOT NULL AND tags != ''")
        all_tags_raw = [row['tags'] for row in cur.fetchall()]
        all_tags = sorted(list(set(tag.strip() for tags in all_tags_raw for tag in tags.split(','))))

        # 동적 쿼리 구성을 위한 준비
        params = []
        where_clauses = []
        base_query = "FROM Question Q LEFT JOIN Choice C ON Q.question_id = C.question_id"

        # 필터 조건 추가
        if search_query:
            where_clauses.append("Q.question_text LIKE ?")
            params.append(f"%{search_query}%")
        if selected_topic:
            where_clauses.append("Q.topic = ?")
            params.append(selected_topic)
        if selected_tag:
            where_clauses.append("Q.tags LIKE ?")
            params.append(f"%{selected_tag}%")

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        # 전체 문제 수 계산
        count_query = "SELECT COUNT(DISTINCT Q.question_id) " + base_query + where_sql
        cur.execute(count_query, params)
        total_questions = cur.fetchone()[0]

        # main_query 초기화
        main_query = "SELECT Q.*, COUNT(CASE WHEN C.is_correct = 1 THEN 1 END) as correct_answer_count " + base_query + where_sql
 
        # 메인 쿼리 실행
        main_query += """
            GROUP BY Q.question_id
            ORDER BY
                CASE WHEN Q.has_error = 1 THEN -1 ELSE 0 END, -- ✨[추가] 오류 신고 문제 최우선 정렬
                CASE WHEN COUNT(CASE WHEN C.is_correct = 1 THEN 1 END) = 0 THEN 0 ELSE 2 END,
                CASE WHEN Q.topic IS NULL OR Q.topic = '' THEN 1 ELSE 2 END,
                Q.question_id DESC
            LIMIT ? OFFSET ?
        """
        query_params = params + [PER_PAGE, offset]
        cur.execute(main_query, query_params)
        questions = cur.fetchall()

    total_pages = (total_questions + PER_PAGE - 1) // PER_PAGE

    # ✨[수정] 모든 필터 관련 변수를 템플릿으로 전달합니다.
    return render_template(
        "manage.html", 
        questions=questions, 
        current_page=page, 
        total_pages=total_pages,
        search_query=search_query,
        all_topics=all_topics,
        all_tags=all_tags,
        selected_topic=selected_topic,
        selected_tag=selected_tag
    )

@app.route("/edit/<int:question_id>", methods=["GET", "POST"])
def edit_question(question_id):
    """개별 문제 수정 (이전/다음 문제 탐색 및 필터 유지 기능 추가)."""
    
    # 목록으로 돌아갈 때 필터를 유지하기 위해 URL 파라미터를 가져옴
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '', type=str)
    selected_topic = request.args.get('topic', '', type=str)
    selected_tag = request.args.get('tag', '', type=str)

    with closing(get_db()) as con:
        # --- POST 요청 처리 (변경사항 저장 버튼을 눌렀을 때) ---
        if request.method == "POST":
            question_text = request.form.get("question_text") 
            subject = request.form.get("subject")
            topic = request.form.get("topic")
            tags = request.form.get("tags")
            answer_explanation = request.form.get("answer_explanation")
            correct_choice_ids = request.form.getlist("correct_choices")
            question_image_path = request.form.get("question_image_path")

            cur = con.cursor()
            cur.execute(
                """
                UPDATE Question 
                SET question_text = ?, subject = ?, topic = ?, tags = ?, answer_explanation = ?, image_path = ?
                WHERE question_id = ?
                """,
                (question_text, subject, topic, tags, answer_explanation, question_image_path, question_id)
            )
            
            cur.execute("SELECT choice_id FROM Choice WHERE question_id = ?", (question_id,))
            choice_ids = [row['choice_id'] for row in cur.fetchall()]
            for cid in choice_ids:
                choice_image_path = request.form.get(f"choice_image_path_{cid}")
                cur.execute("UPDATE Choice SET image_path = ? WHERE choice_id = ?", (choice_image_path, cid))

            if correct_choice_ids:
                correct_ids_int = [int(cid) for cid in correct_choice_ids]
                cur.execute("UPDATE Choice SET is_correct = 0 WHERE question_id = ?", (question_id,))
                
                if correct_ids_int:
                    placeholders = ','.join('?' for _ in correct_ids_int)
                    query = f"UPDATE Choice SET is_correct = 1 WHERE choice_id IN ({placeholders})"
                    cur.execute(query, correct_ids_int)
            
            con.commit()
            flash(f"문제 #{question_id} 정보가 성공적으로 업데이트되었습니다.", "success")
            
            # 수정 완료 후, 필터 파라미터를 포함하여 목록 페이지로 리디렉션
            return redirect(url_for("manage", page=page, q=search_query, topic=selected_topic, tag=selected_tag))

        # --- GET 요청 처리 (수정 페이지에 처음 들어갔을 때) ---
        cur = con.cursor()
        # 현재 문제의 데이터를 가져옴
        cur.execute("SELECT * FROM Question WHERE question_id = ?", (question_id,))
        question = cur.fetchone()

        if not question:
            return "문제를 찾을 수 없습니다.", 404

        # 현재 문제의 선택지 데이터를 가져옴
        cur.execute("SELECT * FROM Choice WHERE question_id = ? ORDER BY choice_id", (question_id,))
        choices = cur.fetchall()
        
        # --- 이전/다음 문제 ID를 찾기 위한 로직 ---
        params = []
        where_clauses = []
        base_query = "FROM Question Q LEFT JOIN Choice C ON Q.question_id = C.question_id"
        
        if search_query:
            where_clauses.append("Q.question_text LIKE ?")
            params.append(f"%{search_query}%")
        if selected_topic:
            where_clauses.append("Q.topic = ?")
            params.append(selected_topic)
        if selected_tag:
            where_clauses.append("Q.tags LIKE ?")
            params.append(f"%{selected_tag}%")

        where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        ordered_query = """
            SELECT Q.question_id
        """ + base_query + where_sql + """
            GROUP BY Q.question_id
            ORDER BY
                CASE WHEN Q.has_error = 1 THEN -1 ELSE 0 END,
                CASE WHEN COUNT(CASE WHEN C.is_correct = 1 THEN 1 END) = 0 THEN 0 ELSE 2 END,
                CASE WHEN Q.topic IS NULL OR Q.topic = '' THEN 1 ELSE 2 END,
                Q.question_id DESC
        """
        cur.execute(ordered_query, params)
        ordered_ids = [row['question_id'] for row in cur.fetchall()]
        
        previous_question_id = None
        next_question_id = None
        try:
            current_index = ordered_ids.index(question_id)
            if current_index > 0:
                previous_question_id = ordered_ids[current_index - 1]
            if current_index < len(ordered_ids) - 1:
                next_question_id = ordered_ids[current_index + 1]
        except ValueError:
            pass

    return render_template(
        "edit_question.html", 
        question=question, 
        choices=choices,
        previous_question_id=previous_question_id,
        next_question_id=next_question_id,
        current_filters={
            'page': page, 
            'q': search_query, 
            'topic': selected_topic, 
            'tag': selected_tag
        }
    )

@app.route("/start_review")
def start_review():
    with closing(get_db()) as con:
        # WrongAnswer 테이블에서 모든 틀린 문제 ID를 가져옴
        cur = con.cursor()
        cur.execute("SELECT question_id FROM WrongAnswer")
        wrong_qids = [row['question_id'] for row in cur.fetchall()]

    if not wrong_qids:
        flash("복습할 오답 문제가 없습니다.", "info")
        return redirect(url_for("index"))

    # 가져온 ID를 바탕으로 문제와 선택지 정보 조회
    questions_with_choices = []
    with closing(get_db()) as con:
        for qid in wrong_qids:
            cur = con.cursor()
            cur.execute("SELECT * FROM Question WHERE question_id = ?", (qid,))
            q = cur.fetchone()
            
            choices_cur = con.cursor()
            choices_cur.execute("SELECT * FROM Choice WHERE question_id = ?", (qid,))
            choices = choices_cur.fetchall()

            correct_answer_count = sum(1 for c in choices if c["is_correct"])

            questions_with_choices.append({
                "question": q,
                "choices": choices,
                "correct_answer_count": correct_answer_count
            })
    
    random.shuffle(questions_with_choices) # 문제 순서 섞기
    session["current_exam"] = [q_wc["question"]["question_id"] for q_wc in questions_with_choices]
    return render_template("exam.html", questions_data=questions_with_choices)

# ✨[추가] 시험 중 정보 수정을 위한 API 라우트
@app.route("/quick_edit/<int:question_id>", methods=["POST"])
def quick_edit(question_id):
    topic = request.form.get("topic")
    tags = request.form.get("tags")

    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute(
            "UPDATE Question SET topic = ?, tags = ? WHERE question_id = ?",
            (topic, tags, question_id)
        )
        con.commit()
    
    # 성공 응답 반환
    return {"status": "success", "message": "업데이트 완료"}

@app.route("/report_error/<int:question_id>", methods=["POST"])
def report_error(question_id):
    with closing(get_db()) as con:
        cur = con.cursor()
        # 현재 오류 상태를 조회하여 반대 값으로 변경 (토글)
        cur.execute("SELECT has_error FROM Question WHERE question_id = ?", (question_id,))
        current_status = cur.fetchone()['has_error']
        new_status = not current_status
        
        cur.execute(
            "UPDATE Question SET has_error = ? WHERE question_id = ?",
            (new_status, question_id)
        )
        con.commit()
    
    return {"status": "success", "has_error": new_status}

@app.route("/history")
def history_list():
    """저장된 시험 기록 목록을 보여줍니다."""
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM TestSession ORDER BY timestamp DESC")
        sessions = cur.fetchall()
    return render_template("history.html", sessions=sessions)

@app.route("/history/<int:session_id>")
def history_detail(session_id):
    """특정 시험 기록의 상세 결과를 보여줍니다."""
    results = []
    session_info = {}

    with closing(get_db()) as con:
        cur = con.cursor()
        
        # 1. 해당 세션의 기본 정보 조회
        cur.execute("SELECT * FROM TestSession WHERE session_id = ?", (session_id,))
        session_info = cur.fetchone()
        if not session_info:
            return "시험 기록을 찾을 수 없습니다.", 404

        # 2. 해당 세션의 모든 사용자 답변 기록 조회
        cur.execute("SELECT * FROM UserAnswer WHERE session_id = ?", (session_id,))
        user_answers = cur.fetchall()

        # 3. 각 답변에 대한 상세 정보 재구성 (results.html 템플릿 형식에 맞게)
        for answer in user_answers:
            qid = answer["question_id"]
            
            # 문제 정보
            q_cur = con.cursor()
            q_cur.execute("SELECT * FROM Question WHERE question_id = ?", (qid,))
            question_row = q_cur.fetchone()

            # 선택지 정보
            c_cur = con.cursor()
            c_cur.execute("SELECT * FROM Choice WHERE question_id = ?", (qid,))
            choices = c_cur.fetchall()

            # 정답 ID 리스트
            correct_choice_ids = [c["choice_id"] for c in choices if c["is_correct"]]
            # 사용자가 선택한 ID 리스트 (JSON 문자열을 다시 리스트로)
            chosen_choice_ids = json.loads(answer["chosen_choice_ids"])

            results.append({
                "question": question_row,
                "choices": choices,
                "chosen": chosen_choice_ids,
                "correct": correct_choice_ids,
                "is_correct": answer["is_correct"],
                "confidence": answer["confidence"]
            })

    return render_template(
        "results.html", 
        results=results, 
        score=session_info["score"], 
        total=session_info["total"], 
        percent=session_info["percent"],
        is_history=True # 다시보기 페이지임을 알리는 플래그
    )

# --- 앱 실행 ---
if __name__ == "__main__":
    app.run(debug=True)