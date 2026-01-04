import json
import os
import time
from datetime import datetime, timedelta

# 引入同级目录下的 db.py
import db

# 别名映射，方便调用
query_db = db.query_db

# ================= 配置 =================
# 文件名保持不变，具体路径在 write_json 中动态计算
JSON_FILENAME = 'available_staff.json'

def scan_available_staff():
    """
    核心扫描逻辑：
    1. 获取当前时间。
    2. 查询所有 shift_settings，判断哪些班次当前是活跃的（active）。
    3. 根据活跃班次，去 roster 表里找人。
    4. 关联 user 表获取姓名。
    5. 生成 JSON。
    """
    now = datetime.now()
    current_time_str = now.strftime('%H:%M')
    today_str = now.strftime('%Y-%m-%d')
    yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')

    try:
        # 1. 获取所有班次配置 (使用 db.py 的 query_db)
        shifts = query_db("SELECT * FROM shift_settings")
        
        # 如果数据库连接失败或没有数据
        if not shifts:
            write_json({})
            return

        active_queries = []  # 存储需要查询的 (shift_id, roster_date)

        # 2. 筛选当前活跃的班次
        for shift in shifts:
            # db.py 返回的是字典，直接通过键访问
            s_id = shift['id']
            start = shift['start_time']
            end = shift['end_time']
            is_next_day = shift['is_next_day']

            if is_next_day == 0:
                # 普通班次：不跨天 (例如 08:00 - 17:00)
                if start <= current_time_str <= end:
                    active_queries.append((s_id, today_str))
            
            else:
                # 跨天班次 (例如 22:00 - 06:00)
                # 情况A：现在是深夜 (例如 23:00)，属于“今天”的排班
                if current_time_str >= start:
                    active_queries.append((s_id, today_str))
                # 情况B：现在是凌晨 (例如 02:00)，属于“昨天”的排班
                elif current_time_str <= end:
                    active_queries.append((s_id, yesterday_str))

        # 如果没有活跃班次，直接写入空对象
        if not active_queries:
            write_json({})
            return

        # 3. 构建查询 roster 的 SQL
        where_clauses = []
        params = []
        for sid, rdate in active_queries:
            where_clauses.append("(r.shift_id = ? AND r.roster_date = ?)")
            params.extend([sid, rdate])
        
        where_sql = " OR ".join(where_clauses)

        # 4. 联表查询：roster -> user
        # 提取字段：部门ID, 用户ID, 用户名
        sql = f"""
            SELECT 
                r.department_id, 
                r.user_id, 
                u.username,
                u.id as user_real_id
            FROM roster r
            JOIN user u ON r.user_id = u.id
            WHERE {where_sql}
        """
        
        rows = query_db(sql, tuple(params))

        if not rows:
            write_json({})
            return

        # 5. 格式化数据
        # 目标格式: { "dept_id": [ {"id": "xxx", "name": "xxx"} ] }
        result_map = {}

        for row in rows:
            dept_id = str(row['department_id'])
            user_info = {
                "id": str(row['user_real_id']),
                "name": row['username']
            }

            if dept_id not in result_map:
                result_map[dept_id] = []
            
            # 去重
            if user_info not in result_map[dept_id]:
                result_map[dept_id].append(user_info)

        # 6. 写入文件
        write_json(result_map)

    except Exception as e:
        print(f"[Error] Staff Scan Failed: {e}")

def write_json(data):
    """
    将数据写入 JSON 文件到【上级目录】
    """
    try:
        # 1. 获取当前脚本所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 2. 获取上级目录 (父目录)
        parent_dir = os.path.dirname(current_dir)
        
        # 3. 拼接目标路径
        target_path = os.path.join(parent_dir, JSON_FILENAME)
        temp_path = os.path.join(parent_dir, JSON_FILENAME + '.tmp')

        # 4. 原子写入 (先写临时文件，再重命名)
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Windows下 rename 需要先删除目标
        if os.path.exists(target_path):
            os.remove(target_path)
        os.rename(temp_path, target_path)
        
        print(f"已更新人员列表: {target_path}")

    except Exception as e:
        print(f"[Error] Writing JSON to parent dir failed: {e}")

if __name__ == "__main__":
    print("Starting manual scan test...")
    scan_available_staff()
    print("Test scan completed.")