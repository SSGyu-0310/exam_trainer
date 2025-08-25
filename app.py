import os
import random
import json
import sqlite3
from contextlib import closing
from flask import Flask, render_template, request, redirect, url_for, session, flash

# --- 앱 설정 ---
app = Flask(__name__)
app.secret_key = "change-me-for-production"

# --- 경로 및 DB 설정 ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "my_database.db")

# --- 데이터베이스 헬퍼 함수 ---
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def get_structured_topics():
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
        session["filters"] = {
            "topics": request.form.getlist("topics"),
            "num_q": int(request.form.get("num_questions") or 5),
            "session_name": request.form.get("session_name") or "이름 없는 시험"
        }
        return redirect(url_for("start_exam"))
    return render_template("index.html",
                           structured_topics=structured_topics,
                           question_counts_json=question_counts_json)

@app.route("/start")
def start_exam():
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
            correct_answer_count = sum(1 for c in choices if c["is_correct"])
            questions_with_choices.append({
                "question": q,
                "choices": choices,
                "correct_answer_count": correct_answer_count
            })
    session["current_exam"] = [q_wc["question"]["question_id"] for q_wc in questions_with_choices]
    labels = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']
    return render_template("exam.html", questions_data=questions_with_choices, labels=labels)

@app.route("/submit", methods=["POST"])
def submit_exam():
    qids = session.get("current_exam", [])
    if not qids:
        return redirect(url_for("index"))
    user_answers = {}
    for qid in qids:
        key = f"q_{qid}"
        user_answers[qid] = [int(val) for val in request.form.getlist(key)]
    results = []
    score = 0
    with closing(get_db()) as con:
        for qid in qids:
            cur = con.cursor()
            cur.execute("SELECT * FROM Question WHERE question_id = ?", (qid,))
            question_row = cur.fetchone()
            cur.execute("SELECT * FROM Choice WHERE question_id = ?", (qid,))
            choices = cur.fetchall()
            correct_choice_ids = [c["choice_id"] for c in choices if c["is_correct"]]
            chosen_choice_ids = user_answers.get(qid, [])
            is_correct = set(chosen_choice_ids) == set(correct_choice_ids)
            if is_correct:
                score += 1
            else:
                check_cur = con.cursor()
                check_cur.execute("SELECT * FROM WrongAnswer WHERE question_id = ?", (qid,))
                if not check_cur.fetchone():
                    con.execute("INSERT INTO WrongAnswer (question_id) VALUES (?)", (qid,))
                    con.commit()
            confidence_value = request.form.get(f"confidence_q_{qid}", -1, type=int)
            con.execute(
                "INSERT INTO AnswerLog (question_id, is_correct, confidence) VALUES (?, ?, ?)",
                (qid, is_correct, confidence_value)
            )
            con.commit()
            results.append({
                "question": question_row,
                "choices": choices,
                "chosen": chosen_choice_ids,
                "correct": correct_choice_ids,
                "is_correct": is_correct,
                "confidence": confidence_value
            })
        total = len(qids)
        percent = int(round(score * 100.0 / total)) if total else 0
        session_name = session.get("filters", {}).get("session_name", "이름 없는 시험")
        session_cur = con.cursor()
        session_cur.execute(
            "INSERT INTO TestSession (session_name, score, total, percent) VALUES (?, ?, ?, ?)",
            (session_name, score, total, percent)
        )
        session_id = session_cur.lastrowid
        con.commit()
        answer_cur = con.cursor()
        for r in results:
            qid = r["question"]["question_id"]
            chosen_ids_json = json.dumps(r["chosen"])
            answer_cur.execute(
                """
                INSERT INTO UserAnswer (session_id, question_id, chosen_choice_ids, is_correct, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, qid, chosen_ids_json, r["is_correct"], r["confidence"])
            )
        con.commit()
    return render_template(
        "results.html",
        results=results,
        score=score,
        total=total,
        percent=percent,
        session_id=session_id
    )

# ... (add_question, manage, edit_question 등 다른 라우트들은 그대로 둡니다) ...
@app.route("/add", methods=["GET", "POST"])
def add_question():
    """새로운 문제를 추가하는 페이지."""
    if request.method == "POST":
        question_text = request.form.get("question_text")
        question_image_path = request.form.get("question_image_path")
        subject = request.form.get("subject")
        topic = request.form.get("topic")
        tags = request.form.get("tags")
        answer_explanation = request.form.get("answer_explanation")

        with closing(get_db()) as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO Question (question_text, image_path, subject, topic, tags, answer_explanation)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (question_text, question_image_path, subject, topic, tags, answer_explanation)
            )
            new_question_id = cur.lastrowid
            
            correct_choices = request.form.getlist("is_correct")
            
            choice_keys = [key for key in request.form if key.endswith('_text')]
            for key in choice_keys:
                choice_id_str = key.replace('_text', '')
                
                choice_text = request.form.get(f"{choice_id_str}_text")
                choice_image = request.form.get(f"{choice_id_str}_image")
                is_correct = (choice_id_str in correct_choices)

                if choice_text:
                    cur.execute(
                        """
                        INSERT INTO Choice (question_id, choice_text, image_path, is_correct)
                        VALUES (?, ?, ?, ?)
                        """,
                        (new_question_id, choice_text, choice_image, is_correct)
                    )
            
            con.commit()

        flash(f"새로운 문제 #{new_question_id}가 성공적으로 추가되었습니다.", "success")
        return redirect(url_for("manage"))

    return render_template("add_question.html")

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
        cur.execute("SELECT DISTINCT topic FROM Question WHERE topic IS NOT NULL AND topic != '' ORDER BY topic")
        all_topics = [row['topic'] for row in cur.fetchall()]
        
        cur.execute("SELECT DISTINCT tags FROM Question WHERE tags IS NOT NULL AND tags != ''")
        all_tags_raw = [row['tags'] for row in cur.fetchall()]
        all_tags = sorted(list(set(tag.strip() for tags in all_tags_raw for tag in tags.split(','))))

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

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        count_query = "SELECT COUNT(DISTINCT Q.question_id) " + base_query + where_sql
        cur.execute(count_query, params)
        total_questions = cur.fetchone()[0]

        main_query = "SELECT Q.*, COUNT(CASE WHEN C.is_correct = 1 THEN 1 END) as correct_answer_count " + base_query + where_sql
 
        main_query += """
            GROUP BY Q.question_id
            ORDER BY
                CASE WHEN Q.has_error = 1 THEN -1 ELSE 0 END,
                CASE WHEN COUNT(CASE WHEN C.is_correct = 1 THEN 1 END) = 0 THEN 0 ELSE 2 END,
                CASE WHEN Q.topic IS NULL OR Q.topic = '' THEN 1 ELSE 2 END,
                Q.question_id DESC
            LIMIT ? OFFSET ?
        """
        query_params = params + [PER_PAGE, offset]
        cur.execute(main_query, query_params)
        questions = cur.fetchall()

    total_pages = (total_questions + PER_PAGE - 1) // PER_PAGE

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
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '', type=str)
    selected_topic = request.args.get('topic', '', type=str)
    selected_tag = request.args.get('tag', '', type=str)

    with closing(get_db()) as con:
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
            
            return redirect(url_for("manage", page=page, q=search_query, topic=selected_topic, tag=selected_tag))

        cur = con.cursor()
        cur.execute("SELECT * FROM Question WHERE question_id = ?", (question_id,))
        question = cur.fetchone()

        if not question:
            return "문제를 찾을 수 없습니다.", 404

        cur.execute("SELECT * FROM Choice WHERE question_id = ? ORDER BY choice_id", (question_id,))
        choices = cur.fetchall()
        
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
        cur = con.cursor()
        cur.execute("SELECT question_id FROM WrongAnswer")
        wrong_qids = [row['question_id'] for row in cur.fetchall()]

    if not wrong_qids:
        flash("복습할 오답 문제가 없습니다.", "info")
        return redirect(url_for("index"))

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
    
    random.shuffle(questions_with_choices)
    session["current_exam"] = [q_wc["question"]["question_id"] for q_wc in questions_with_choices]
    return render_template("exam.html", questions_data=questions_with_choices)

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
    
    return {"status": "success", "message": "업데이트 완료"}

@app.route("/report_error/<int:question_id>", methods=["POST"])
def report_error(question_id):
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute("SELECT has_error FROM Question WHERE question_id = ?", (question_id,))
        current_status = cur.fetchone()['has_error']
        new_status = not current_status
        
        cur.execute(
            "UPDATE Question SET has_error = ? WHERE question_id = ?",
            (new_status, question_id)
        )
        con.commit()
    
    return {"status": "success", "has_error": new_status}


# --- 시험 기록 관련 라우트 ---

@app.route("/review_wrong_answers/<int:session_id>")
def review_wrong_answers(session_id):
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT question_id FROM UserAnswer WHERE session_id = ? AND is_correct = 0",
            (session_id,)
        )
        wrong_qids = [row['question_id'] for row in cur.fetchall()]
    if not wrong_qids:
        flash("이 시험에서는 틀린 문제가 없습니다!", "info")
        return redirect(url_for('history_detail', session_id=session_id))
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
    random.shuffle(questions_with_choices)
    session["current_exam"] = [q_wc["question"]["question_id"] for q_wc in questions_with_choices]
    session["filters"] = {
        "session_name": f"시험 #{session_id} 오답 복습"
    }
    return redirect(url_for('start_exam'))

@app.route("/review_selected", methods=["POST"])
def review_selected_sessions():
    selected_session_ids = request.form.getlist("session_ids")
    if not selected_session_ids:
        flash("복습할 시험을 하나 이상 선택해주세요.", "warning")
        return redirect(url_for("history_list"))
    all_wrong_qids = set()
    with closing(get_db()) as con:
        cur = con.cursor()
        for session_id in selected_session_ids:
            cur.execute(
                "SELECT question_id FROM UserAnswer WHERE session_id = ? AND is_correct = 0",
                (session_id,)
            )
            wrong_qids_in_session = {row['question_id'] for row in cur.fetchall()}
            all_wrong_qids.update(wrong_qids_in_session)
    if not all_wrong_qids:
        flash("선택하신 시험에는 틀린 문제가 없습니다.", "info")
        return redirect(url_for("history_list"))
    questions_with_choices = []
    with closing(get_db()) as con:
        for qid in all_wrong_qids:
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
    random.shuffle(questions_with_choices)
    session["current_exam"] = [q_wc["question"]["question_id"] for q_wc in questions_with_choices]
    session_names = ", ".join([f"#{s_id}" for s_id in selected_session_ids])
    session["filters"] = {
        "session_name": f"시험 {session_names} 오답 복습"
    }
    return redirect(url_for('start_exam'))

@app.route("/history")
def history_list():
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM TestSession ORDER BY timestamp DESC")
        sessions = cur.fetchall()
    return render_template("history.html", sessions=sessions)

@app.route("/history/<int:session_id>")
def history_detail(session_id):
    results = []
    session_info = {}
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM TestSession WHERE session_id = ?", (session_id,))
        session_info = cur.fetchone()
        if not session_info:
            return "시험 기록을 찾을 수 없습니다.", 404
            
        # ✨[수정] 기존 노트들을 한번에 불러오기
        notes_cur = con.cursor()
        notes_cur.execute("SELECT question_id, note_text FROM UserNote WHERE session_id = ?", (session_id,))
        notes_by_qid = {row['question_id']: row['note_text'] for row in notes_cur.fetchall()}

        cur.execute("SELECT * FROM UserAnswer WHERE session_id = ?", (session_id,))
        user_answers = cur.fetchall()
        for answer in user_answers:
            qid = answer["question_id"]
            q_cur = con.cursor()
            q_cur.execute("SELECT * FROM Question WHERE question_id = ?", (qid,))
            question_row = q_cur.fetchone()
            c_cur = con.cursor()
            c_cur.execute("SELECT * FROM Choice WHERE question_id = ?", (qid,))
            choices = c_cur.fetchall()
            correct_choice_ids = [c["choice_id"] for c in choices if c["is_correct"]]
            chosen_choice_ids = json.loads(answer["chosen_choice_ids"])
            
            # ✨[수정] 결과 객체에 노트 정보 추가
            results.append({
                "question": question_row,
                "choices": choices,
                "chosen": chosen_choice_ids,
                "correct": correct_choice_ids,
                "is_correct": answer["is_correct"],
                "confidence": answer["confidence"],
                "note": notes_by_qid.get(qid, "") # 해당 문제의 노트를 전달
            })
            
    return render_template(
        "results.html",
        results=results,
        score=session_info["score"],
        total=session_info["total"],
        percent=session_info["percent"],
        session_id=session_id # ✨[추가] 노트 저장을 위해 session_id 전달
    )

@app.route("/history/edit/<int:session_id>", methods=["POST"])
def edit_history(session_id):
    new_name = request.form.get("new_name")
    if not new_name:
        return {"status": "error", "message": "새로운 이름이 필요합니다."}, 400
    with closing(get_db()) as con:
        cur = con.cursor()
        cur.execute("UPDATE TestSession SET session_name = ? WHERE session_id = ?", (new_name, session_id))
        con.commit()
    flash(f"시험 #{session_id}의 이름이 '{new_name}'(으)로 변경되었습니다.", "success")
    return redirect(url_for("history_list"))

@app.route("/history/delete/<int:session_id>", methods=["POST"])
def delete_history(session_id):
    with closing(get_db()) as con:
        cur = con.cursor()
        # ✨[추가] 관련 노트도 함께 삭제
        cur.execute("DELETE FROM UserNote WHERE session_id = ?", (session_id,))
        cur.execute("DELETE FROM UserAnswer WHERE session_id = ?", (session_id,))
        cur.execute("DELETE FROM TestSession WHERE session_id = ?", (session_id,))
        con.commit()
    flash(f"시험 #{session_id} 기록이 삭제되었습니다.", "success")
    return redirect(url_for("history_list"))

# ✨[추가] 노트 저장/업데이트를 위한 API 엔드포인트
@app.route("/save_note", methods=["POST"])
def save_note():
    data = request.json
    session_id = data.get("session_id")
    question_id = data.get("question_id")
    note_text = data.get("note_text")

    if not all([session_id, question_id]):
        return {"status": "error", "message": "필요한 정보가 누락되었습니다."}, 400

    with closing(get_db()) as con:
        cur = con.cursor()
        # 이미 노트가 있는지 확인 (UPSERT 기능 사용)
        cur.execute(
            """
            INSERT INTO UserNote (session_id, question_id, note_text)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, question_id) DO UPDATE SET
            note_text = excluded.note_text;
            """,
            (session_id, question_id, note_text)
        )
        con.commit()
    
    return {"status": "success", "message": "노트가 저장되었습니다."}

# --- 앱 실행 ---
if __name__ == "__main__":
    app.run(debug=True)