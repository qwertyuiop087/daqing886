import sqlite3

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS cards(
id INTEGER PRIMARY KEY AUTOINCREMENT,
price INTEGER,
card TEXT,
status INTEGER
)
""")

conn.commit()

def add_card(price, card):

    cursor.execute(
        "INSERT INTO cards(price,card,status) VALUES(?,?,0)",
        (price, card)
    )

    conn.commit()


def get_card(price):

    cursor.execute(
        "SELECT id,card FROM cards WHERE price=? AND status=0 LIMIT 1",
        (price,)
    )

    row = cursor.fetchone()

    if row:

        cursor.execute(
            "UPDATE cards SET status=1 WHERE id=?",
            (row[0],)
        )

        conn.commit()

        return row[1]

    return None


def stock(price):

    cursor.execute(
        "SELECT COUNT(*) FROM cards WHERE price=? AND status=0",
        (price,)
    )

    return cursor.fetchone()[0]
