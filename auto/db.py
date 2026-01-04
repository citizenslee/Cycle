import sqlite3
import os

# ================= 数据库路径配置 =================
# os.path.abspath(__file__) 获取当前文件绝对路径
# 第1个 dirname: 获取当前文件所在的文件夹
# 第2个 dirname: 获取上一层文件夹 (父目录)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE = os.path.join(BASE_DIR, 'workorders.db')

print(f"当前数据库路径: {DATABASE}")  # 打印出来检查一下是否正确

def get_connection():
    """获取一个新的数据库连接"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"[DB Error] 连接数据库失败: {e}")
        return None

def query_db(query, args=(), one=False):
    conn = get_connection()
    if not conn:
        return None
    result = None
    try:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        cur.close()
        result = [dict(row) for row in rv]
    except Exception as e:
        print(f"[DB Query Error] SQL: {query} | Args: {args} | Error: {e}")
    finally:
        conn.close()
    if one:
        return result[0] if result else None
    return result

def execute_transaction(operations):
    conn = get_connection()
    if not conn:
        return False, "无法连接数据库"
    try:
        for query, args in operations:
            conn.execute(query, args)
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def modify_db(query, args=()):
    operations = [(query, args)]
    success, msg = execute_transaction(operations)
    return success, msg