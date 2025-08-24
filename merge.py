import sqlite3
import os

# --- ⚙️ 설정 ---
SOURCE_DB_PATH = "22_Diag.db" 
DEST_DB_PATH = os.path.join("data", "my_database.db")

# ----------------------------------------------------

# ✨[추가] 이미지 삭제를 위한 헬퍼 함수
def delete_associated_images(q_row, source_cursor):
    """주어진 문제(q_row) 및 그 선택지들과 연관된 모든 이미지 파일을 삭제합니다."""
    
    image_paths_to_delete = []

    # 1. 문제 자체의 이미지 경로 수집
    if q_row["image_path"]:
        # 쉼표로 구분된 여러 이미지 경로를 처리하기 위해 split 사용
        image_paths_to_delete.extend(q_row["image_path"].split(','))

    # 2. 해당 문제에 속한 모든 선택지의 이미지 경로 수집
    source_cursor.execute("SELECT image_path FROM Choice WHERE question_id = ?", (q_row["question_id"],))
    choice_images = source_cursor.fetchall()
    for c_row in choice_images:
        if c_row["image_path"]:
            image_paths_to_delete.extend(c_row["image_path"].split(','))

    # 3. 수집된 경로의 파일들을 실제로 삭제
    deleted_count = 0
    for img_path in image_paths_to_delete:
        # 경로 문자열의 앞뒤 공백 제거
        clean_path = img_path.strip()
        if clean_path and os.path.exists(clean_path):
            try:
                os.remove(clean_path)
                print(f"    - 이미지 삭제: {clean_path}")
                deleted_count += 1
            except OSError as e:
                print(f"    - 이미지 삭제 오류: {e}")
    
    if deleted_count == 0:
        print("    - 삭제할 연관 이미지가 없습니다.")


def merge_databases():
    if not os.path.exists(SOURCE_DB_PATH):
        print(f"오류: 원본 데이터베이스 '{SOURCE_DB_PATH}'를 찾을 수 없습니다.")
        return

    if not os.path.exists(DEST_DB_PATH):
        print(f"오류: 대상 데이터베이스 '{DEST_DB_PATH}'를 찾을 수 없습니다.")
        return

    source_con = sqlite3.connect(SOURCE_DB_PATH)
    source_con.row_factory = sqlite3.Row
    source_cur = source_con.cursor()

    dest_con = sqlite3.connect(DEST_DB_PATH)
    dest_cur = dest_con.cursor()

    print(f"'{SOURCE_DB_PATH}'에서 '{DEST_DB_PATH}'로 데이터 병합을 시작합니다.")

    source_cur.execute("SELECT * FROM Question")
    source_questions = source_cur.fetchall()

    imported_count = 0
    skipped_count = 0

    for q_row in source_questions:
        question_text = q_row["question_text"]
        dest_cur.execute("SELECT question_id FROM Question WHERE question_text = ?", (question_text,))
        existing_question = dest_cur.fetchone()

        # ✨[수정] 중복 발견 시 자동 건너뛰기 대신 사용자에게 확인 요청
        if existing_question:
            print("-" * 50)
            print(f"⚠️  중복 의심 문제 발견:")
            print(f"   '{question_text[:80]}...'")
            
            # 사용자에게 직접 물어봄
            while True:
                choice = input("-> 이 문제를 건너뛰고 관련 이미지를 삭제하시겠습니까? (y/n): ").lower().strip()
                if choice in ['y', 'n']:
                    break
                print("   'y' 또는 'n'으로만 입력해주세요.")

            if choice == 'y':
                print("-> 사용자가 건너뛰기를 선택했습니다. 연관된 이미지 파일 삭제를 시도합니다.")
                # ✨[호출] 이미지 삭제 함수 호출
                delete_associated_images(q_row, source_cur)
                skipped_count += 1
                print("-" * 50)
                continue # 다음 문제로 넘어감
            else:
                print("-> 사용자가 강제 추가를 선택했습니다. 문제를 데이터베이스에 추가합니다.")
                # 'n'를 선택하면, 아래의 문제 추가 로직이 그대로 실행됨
        
        # --- 문제 추가 로직 (중복이 아니거나, 사용자가 강제 추가를 선택한 경우 실행) ---
        dest_cur.execute(
            """
            INSERT INTO Question (question_text, image_path, subject, topic, answer_explanation, author, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                q_row["question_text"], q_row["image_path"], q_row["subject"],
                q_row["topic"], q_row["answer_explanation"], q_row["author"], q_row["tags"]
            )
        )
        new_question_id = dest_cur.lastrowid

        source_cur.execute("SELECT * FROM Choice WHERE question_id = ?", (q_row["question_id"],))
        source_choices = source_cur.fetchall()

        for c_row in source_choices:
            dest_cur.execute(
                """
                INSERT INTO Choice (question_id, choice_text, image_path, is_correct)
                VALUES (?, ?, ?, ?)
                """,
                (new_question_id, c_row["choice_text"], c_row["image_path"], c_row["is_correct"])
            )
        
        imported_count += 1
        print(f"-> 문제 추가 완료: '{question_text[:30]}...'")
        if existing_question: # 강제 추가된 경우, 메시지를 한 번 더 명확히 보여줌
             print("-" * 50)


    dest_con.commit()
    source_con.close()
    dest_con.close()

    print("\n--- ✅ 병합 완료 ---")
    print(f"총 {imported_count}개의 새로운 문제가 추가되었습니다.")
    print(f"총 {skipped_count}개의 중복 문제가 사용자 확인 후 건너뛰어졌습니다.")

if __name__ == "__main__":
    merge_databases()