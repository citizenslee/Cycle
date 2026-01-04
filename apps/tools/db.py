# db.py
import sqlite3
from flask import g

DATABASE = 'workorders.db' 

# --- 数据库辅助函数 ---

def get_db():
    """获取数据库连接"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # 设置 row_factory 可以让我们像字典一样访问列名 (row['id'])
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    """通用查询函数"""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    # 将 sqlite3.Row 对象转换为普通字典，方便 json 序列化
    result = [dict(row) for row in rv]
    return (result[0] if result else None) if one else result

def modify_db(query, args=()):
    """通用增删改函数，自动提交事务 (适用于单条SQL)"""
    db = get_db()
    try:
        cur = db.execute(query, args)
        db.commit()
        last_id = cur.lastrowid # 获取自增ID
        cur.close()
        return True, last_id
    except Exception as e:
        db.rollback()
        return False, str(e)

def execute_transaction(operations):
    """
    通用事务执行函数：一次性执行多条 SQL，保证原子性 (要么全成，要么全败)
    
    :param operations: list, 包含多个元组 [(query, args), (query, args), ...]
    :return: (True, None) 或 (False, error_msg)
    """
    db = get_db()
    try:
        # 遍历操作列表，依次执行
        for query, args in operations:
            db.execute(query, args)
        
        # 所有语句执行无误后，统一提交
        db.commit()
        return True, None
    except Exception as e:
        # 只要有一条报错，立即回滚所有操作
        db.rollback()
        return False, str(e)