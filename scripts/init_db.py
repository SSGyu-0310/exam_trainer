import sqlite3, os, json

BASE = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE, "data", "questions.db")
SCHEMA = os.path.join(BASE, "scripts", "schema.sql")
SEED = [
    {
        "subject": "수학",
        "topic": "미분",
        "question_text": "함수 f(x)=x^2의 도함수 f'(x)는 무엇인가?",
        "option_a": "x",
        "option_b": "2x",
        "option_c": "x^3",
        "option_d": "상수 2",
        "correct_option": "B",
        "pdf_path": None,
        "pdf_page": None
    },
    {
        "subject": "수학",
        "topic": "적분",
        "question_text": "∫ 2x dx 의 결과는? (적분상수 C 제외)",
        "option_a": "x^2",
        "option_b": "x^2 + C",
        "option_c": "x^3",
        "option_d": "x^3 + C",
        "correct_option": "A",
        "pdf_path": None,
        "pdf_page": None
    },
    {
        "subject": "과학",
        "topic": "물리-역학",
        "question_text": "등속직선운동에서 속도가 의미하는 것은?",
        "option_a": "위치의 시간에 대한 변화율",
        "option_b": "가속도의 시간에 대한 변화율",
        "option_c": "힘의 시간에 대한 변화율",
        "option_d": "질량의 시간에 대한 변화율",
        "correct_option": "A",
        "pdf_path": None,
        "pdf_page": None
    }
]

def main():
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    with open(SCHEMA, "r", encoding="utf-8") as f:
        con.executescript(f.read())

    cur = con.cursor()
    cur.executemany(
        """INSERT INTO questions
        (subject, topic, question_text, option_a, option_b, option_c, option_d, correct_option, pdf_path, pdf_page)
        VALUES (:subject,:topic,:question_text,:option_a,:option_b,:option_c,:option_d,:correct_option,:pdf_path,:pdf_page)""",
        SEED
    )
    con.commit()
    con.close()
    print("Database created with seed rows at:", DB_PATH)

if __name__ == "__main__":
    main()
