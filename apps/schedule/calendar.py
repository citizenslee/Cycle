from flask import render_template, request, jsonify
from apps.tools.db import query_db, modify_db, execute_transaction
from datetime import date, timedelta
import calendar
from .route import bp_schedule
from apps.tools.permissions import get_current_user_info
   
   # 渲染主页面框架
@bp_schedule.route('/custom_calendar')
def view_custom_calendar():
    user = get_current_user_info()
    dept_id = user['id_department']
    dept_name = user.get('department_name', '')
    
    # 获取员工列表供下拉框
    # 注意：根据你的逻辑，可能需要过滤 staff_flag
    users = query_db(
        "SELECT id, username FROM user WHERE staff_flag = 1 AND id_department = ? ORDER BY id",
        (dept_id,)
    )
    
    # 默认显示当前年月
    today = date.today()
    
    # 传递 dept_name 供前端显示 (假设前端模板有 {{ dept_name }})
    return render_template('schedule/calendar.html', 
                           users=users, 
                           default_year=today.year, 
                           default_month=today.month,
                           dept_id=dept_id,
                           dept_name=dept_name)

@bp_schedule.route('/api/auto_schedule', methods=['POST'])
def auto_schedule():
    data = request.json
    try:
        year = int(data.get('year'))
        month = int(data.get('month'))
    except (ValueError, TypeError):
        return jsonify({"success": False, "msg": "年份或月份格式错误"}), 400

    user_info = get_current_user_info()
    dept_id = str(user_info.get('id_department'))
    start_user_id = data.get('start_user_id')

    print(f"--- 智能排班: {year}-{month} (部门: {dept_id}) ---")

    # ================= 1. 获取配置 (保持不变) =================
    shift_rows = query_db("""
        SELECT id, name, workday_mode, weekend_mode, 
               duty_count, fixed_user_ids, exclude_user_ids 
        FROM shift_settings 
        WHERE id_department = ?
    """, (dept_id,))
    
    if not shift_rows:
        return jsonify({"success": False, "msg": "未找到班次配置"}), 400

    all_users_rows = query_db("SELECT id FROM user WHERE id_department = ? AND staff_flag = 1", (dept_id,))
    all_staff_ids = [row['id'] for row in all_users_rows]

    # 获取轮转表
    shift_rotation_map = {}
    rotation_rows = query_db("""
        SELECT shift_id, user_id 
        FROM schedule_rotation 
        WHERE dept_id = ? 
        ORDER BY shift_id, priority ASC
    """, (dept_id,))
    
    for row in rotation_rows:
        sid = row['shift_id']
        if sid not in shift_rotation_map:
            shift_rotation_map[sid] = []
        shift_rotation_map[sid].append(row['user_id'])

    # 获取日历例外
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)
    
    exception_rows = query_db("""
        SELECT exception_date, type FROM calendar_exception
        WHERE dept_id = ? AND exception_date BETWEEN ? AND ?
    """, (dept_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
    exception_map = {r["exception_date"]: r["type"] for r in exception_rows}

    # ================= 2. 初始化指针 (保持不变) =================
    shift_pointers = {row['id']: 0 for row in shift_rows}

    # 断点续传
    last_roster = query_db("""
        SELECT roster_date FROM roster 
        WHERE department_id = ? 
        ORDER BY roster_date DESC LIMIT 1
    """, (dept_id,), one=True)
    
    if last_roster and not start_user_id:
        last_date_str = last_roster['roster_date']
        last_assignments = query_db("""
            SELECT shift_id, user_id FROM roster 
            WHERE department_id = ? AND roster_date = ?
        """, (dept_id, last_date_str))
        
        for assign in last_assignments:
            sid = assign['shift_id']
            uid = assign['user_id']
            if sid in shift_rotation_map and uid in shift_rotation_map[sid]:
                # 找到该人在列表中的位置，指向下一位
                # index() 只返回第一个匹配项，但在有序列表中通常没问题
                curr_idx = shift_rotation_map[sid].index(uid)
                next_idx = curr_idx + 1
                # 仅当新的位置比当前记录的更靠后时更新（防止同日多班次导致的乱序，取最大值）
                if next_idx > shift_pointers.get(sid, 0):
                    shift_pointers[sid] = next_idx

    if start_user_id:
        target_uid = int(start_user_id)
        for sid, u_list in shift_rotation_map.items():
            if target_uid in u_list:
                shift_pointers[sid] = u_list.index(target_uid)

    # ================= 3. 执行排班循环 =================
    ops = [("DELETE FROM roster WHERE department_id = ? AND roster_date BETWEEN ? AND ?", 
           (dept_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))]

    curr = start_date
    while curr <= end_date:
        date_str = curr.strftime('%Y-%m-%d')
        
        # A. 判定日期类型
        is_weekend = curr.weekday() >= 5
        day_type = exception_map.get(date_str)
        is_holiday_logic = (day_type == "HOLIDAY") or (is_weekend and day_type != "WORKDAY")

        # B. 【核心逻辑更新】确定今日轮值组并同步指针
        today_duty_users = [] 
        
        # 1. 找出今天所有 DUTY 班次
        today_duty_shifts = []
        for shift in shift_rows:
            mode = shift['weekend_mode'] if is_holiday_logic else shift['workday_mode']
            if mode == 'DUTY':
                today_duty_shifts.append(shift)
        
        # 2. 选人 (从第一个有效的数据源班次选)
        if today_duty_shifts:
            source_shift = None
            source_list = []
            
            # 寻找数据源
            for s in today_duty_shifts:
                if s['id'] in shift_rotation_map and shift_rotation_map[s['id']]:
                    source_shift = s
                    source_list = shift_rotation_map[s['id']]
                    break 
            
            # 如果找到了数据源，计算人员
            if source_shift:
                sid = source_shift['id']
                count = source_shift['duty_count'] if source_shift['duty_count'] else 1
                ptr = shift_pointers[sid]
                
                excludes = []
                if source_shift["exclude_user_ids"]:
                    excludes = [int(x) for x in str(source_shift["exclude_user_ids"]).split(",") if x.strip()]

                selected = []
                searched_steps = 0
                list_len = len(source_list)
                
                # 循环取人
                while len(selected) < count and searched_steps < list_len:
                    idx = (ptr + searched_steps) % list_len
                    uid = source_list[idx]
                    if uid not in excludes:
                        selected.append(uid)
                    searched_steps += 1
                
                today_duty_users = selected
            
            # 3. 【更新所有相关班次的指针】
            # 无论该班次是否是数据源，只要它是 DUTY 且包含今天选中的人，就更新指针
            for duty_shift in today_duty_shifts:
                d_sid = duty_shift['id']
                # 如果这个班次有轮转表
                if d_sid in shift_rotation_map and shift_rotation_map[d_sid]:
                    d_list = shift_rotation_map[d_sid]
                    d_len = len(d_list)
                    
                    # 遍历今天选中的每一个人，逐步推移指针
                    # 逻辑：如果张三上班了，指针就应该在张三后面
                    for worked_uid in today_duty_users:
                        if worked_uid in d_list:
                            # 找到该人在本班次列表中的索引
                            u_idx = d_list.index(worked_uid)
                            # 将指针强制更新为该人之后的一位
                            # 这样即使本班次今天是被迫跟随别人的，它也“记录”了这个人已值班
                            shift_pointers[d_sid] = (u_idx + 1) % d_len

        # C. 遍历今日班次进行填充
        for shift in shift_rows:
            sid = shift['id']
            mode = shift['weekend_mode'] if is_holiday_logic else shift['workday_mode']

            users_to_write = []

            if mode == 'DUTY':
                users_to_write = today_duty_users

            elif mode == 'FIXED':
                if shift["fixed_user_ids"]:
                    users_to_write = [int(x) for x in str(shift["fixed_user_ids"]).split(",") if x.strip()]

            elif mode == 'ALL':
                this_excludes = []
                if shift["exclude_user_ids"]:
                    this_excludes = [int(x) for x in str(shift["exclude_user_ids"]).split(",") if x.strip()]
                users_to_write = [u for u in all_staff_ids if u not in this_excludes]

            for uid in users_to_write:
                ops.append(("INSERT INTO roster (roster_date, shift_id, user_id, department_id) VALUES (?, ?, ?, ?)", 
                           (date_str, sid, uid, dept_id)))

        curr += timedelta(days=1)
    # ================= 4. 提交 =================
    try:
        execute_transaction(ops) 
        return jsonify({"success": True, "msg": "排班成功"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500
    

@bp_schedule.route('/api/rest', methods=['POST'])
def rest_shift():
    """员工休息（删除排班记录）接口"""
    data = request.json
    roster_date = data.get('roster_date')
    shift_id = data.get('shift_id')
    user_id = data.get('user_id')
    
    # 增加部门校验，防止跨部门操作
    user_info = get_current_user_info()
    dept_id = user_info.get('id_department')

    # 1. 核心校验：检查当前班次还有几个人 (同部门)
    check_sql = "SELECT count(*) as c FROM roster WHERE roster_date = ? AND shift_id = ? AND department_id = ?"
    res = query_db(check_sql, (roster_date, shift_id, dept_id), one=True)
    
    current_count = res['c'] if res else 0

    if current_count <= 1:
        return jsonify({
            "success": False, 
            "msg": "操作失败：该班次当前仅剩 1 人，无法休息，请先使用【替班】或【加人】。"
        })

    # 2. 执行删除
    del_sql = "DELETE FROM roster WHERE roster_date = ? AND shift_id = ? AND user_id = ? AND department_id = ?"
    success, _ = modify_db(del_sql, (roster_date, shift_id, user_id, dept_id))

    if success:
        return jsonify({"success": True, "msg": "休息申请已通过"})
    else:
        return jsonify({"success": False, "msg": "数据库操作失败"})
    
@bp_schedule.route('/api/substitute', methods=['POST'])
def substitute_shift():
    """
    替班接口：修改 roster 表
    """
    data = request.json
    roster_date = data.get('roster_date')
    shift_id = data.get('shift_id')
    old_user_id = data.get('old_user_id')
    new_user_id = data.get('new_user_id')
    
    user_info = get_current_user_info()
    dept_id = user_info.get('id_department')

    # 0. 基础参数校验
    if not all([roster_date, shift_id, old_user_id, new_user_id]):
        return jsonify({"success": False, "msg": "参数不完整"})
    
    # 1. 逻辑校验：检查[新人员]是否已经在该班次中
    check_sql = "SELECT count(*) as c FROM roster WHERE roster_date = ? AND shift_id = ? AND user_id = ? AND department_id = ?"
    check_res = query_db(check_sql, (roster_date, shift_id, new_user_id, dept_id), one=True)
    
    if check_res and check_res['c'] > 0:
        return jsonify({
            "success": False, 
            "msg": "操作失败：目标替班人员已经在该班次中，不可重复排班。"
        })

    # 2. 执行更新
    update_sql = """
        UPDATE roster 
        SET user_id = ? 
        WHERE roster_date = ? AND shift_id = ? AND user_id = ? AND department_id = ?
    """
    success, err = modify_db(update_sql, (new_user_id, roster_date, shift_id, old_user_id, dept_id))

    if success:
        return jsonify({"success": True, "msg": "替班成功"})
    else:
        return jsonify({"success": False, "msg": f"数据库操作失败: {err}"})

@bp_schedule.route('/api/add_staff', methods=['POST'])
def add_staff_shift():
    """
    加人接口：插入 roster 表
    """
    data = request.json
    roster_date = data.get('roster_date')
    shift_id = data.get('shift_id')
    user_id = data.get('user_id')
    
    user_info = get_current_user_info()
    dept_id = user_info.get('id_department')

    if not all([roster_date, shift_id, user_id]):
        return jsonify({"success": False, "msg": "参数不完整"})

    # 1. 查重
    check_sql = "SELECT count(*) as c FROM roster WHERE roster_date = ? AND shift_id = ? AND user_id = ? AND department_id = ?"
    check_res = query_db(check_sql, (roster_date, shift_id, user_id, dept_id), one=True)
    
    if check_res and check_res['c'] > 0:
        return jsonify({
            "success": False, 
            "msg": "该员工已在当前班次中。"
        })

    # 2. 插入 (注意包含 department_id)
    insert_sql = "INSERT INTO roster (roster_date, shift_id, user_id, department_id) VALUES (?, ?, ?, ?)"
    success, err = modify_db(insert_sql, (roster_date, shift_id, user_id, dept_id))

    if success:
        return jsonify({"success": True, "msg": "人员添加成功"})
    else:
        return jsonify({"success": False, "msg": f"数据库操作失败: {err}"})

# 接口：获取排班数据给前端日历显示
@bp_schedule.route('/api/get_calendar_html')
def get_calendar_html():
    year = int(request.args.get('year'))
    month = int(request.args.get('month'))
    
    user_info = get_current_user_info()
    dept_id = user_info.get('id_department')

    start_date = date(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    end_date = date(year, month, last_day)
    
    # 1. 获取排班数据 (保持原有逻辑)
    sql = """
        SELECT 
            r.roster_date, r.shift_id, r.user_id,
            u.username,
            s.name as shift_name, s.color, s.start_time, s.end_time
        FROM roster r
        JOIN user u ON r.user_id = u.id
        JOIN shift_settings s ON r.shift_id = s.id
        WHERE r.department_id = ?
          AND r.roster_date BETWEEN ? AND ?
        ORDER BY s.start_time ASC
    """
    rows = query_db(sql, (dept_id, start_date, end_date))
    
    data_map = {}
    # ... (此处保持原有的 data_map 组装逻辑不变) ...
    for r in rows:
        d_str = r['roster_date']
        s_id = r['shift_id']
        if d_str not in data_map: data_map[d_str] = {}
        if s_id not in data_map[d_str]:
            data_map[d_str][s_id] = {
                'shift_name': r['shift_name'],
                'color': r['color'] if r['color'] else '#1E9FFF',
                'time': f"{r['start_time']}-{r['end_time']}",
                'users': [],
                'raw_shift_id': s_id
            }
        data_map[d_str][s_id]['users'].append({'uid': r['user_id'], 'name': r['username']})

    # === 【新增】2. 获取节假日/调休配置 ===
    exc_sql = "SELECT exception_date, type, note FROM calendar_exception WHERE dept_id = ? AND exception_date BETWEEN ? AND ?"
    exc_rows = query_db(exc_sql, (dept_id, start_date, end_date))
    
    # 组装成字典: exception_map['2024-05-01'] = {'type': 'HOLIDAY', 'note': '劳动节'}
    exception_map = {
        row['exception_date']: {'type': row['type'], 'note': row['note']} 
        for row in exc_rows
    }

    cal_matrix = calendar.monthcalendar(year, month)
    
    # 传入 exception_map
    return render_template('schedule/_calendar_grid.html', 
                           year=year, month=month, 
                           cal_matrix=cal_matrix, 
                           data_map=data_map,
                           exception_map=exception_map) # <--- 新增参数