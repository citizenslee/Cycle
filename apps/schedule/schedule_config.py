from flask import Blueprint, render_template, request, jsonify, g
from apps.tools.db import query_db, modify_db
from apps.tools.permissions import get_current_user_info
import json
from .route import bp_schedule

# ======================= 工具函数 =======================

def get_dept_users_map(dept_id):
    """
    获取部门下所有用户，返回 {str(id): username} 的字典
    用于将数据库存储的 '1,2,3' 转为 '张三,李四,王五'
    """
    sql = "SELECT id, username FROM user WHERE id_department = ? AND staff_flag = '1' "
    users = query_db(sql, (dept_id,))
    return {str(u['id']): u['username'] for u in users}

# ======================= 1. 页面渲染 =======================

@bp_schedule.route('/config')
def config_page():
    """ 渲染排班配置主页面 """
    user_info = get_current_user_info()
    dept_id = user_info.get('id_department')
    dept_name = user_info.get('department_name')
    hospital_name = user_info.get('hospital_name')
    # 获取该部门所有用户，用于前端人员选择器
    sql_users = "SELECT id, username FROM user WHERE id_department = ? AND staff_flag = 1 "
    users = query_db(sql_users, (dept_id,))

    return render_template('schedule/schedule_config.html', dept_id=dept_id, hospital_name=hospital_name, dept_name=dept_name, users=users)


# ======================= 2. 核心数据接口 (班次+规则合并查询) =======================

@bp_schedule.route('/api/config/list', methods=['GET'])
def api_config_list():
    """
    获取班次列表及配置信息
    由于表已合并，直接查询 shift_settings 即可，无需 JOIN
    """
    dept_id = request.args.get('dept_id')
    
    # 获取用户ID到名称的映射
    user_map = get_dept_users_map(dept_id)

    # 直接查询合并后的 shift_settings 表
    sql = """
        SELECT 
            id, name, color, start_time, end_time, is_next_day,
            workday_mode, weekend_mode, duty_count, 
            fixed_user_ids, exclude_user_ids
        FROM shift_settings
        WHERE id_department = ?
        ORDER BY start_time ASC
    """
    rows = query_db(sql, (dept_id,))
    
    result = []
    for r in rows:
        row_dict = dict(r)
        
        # 处理默认值 (防止数据库存的是 NULL)
        if not row_dict['workday_mode']: row_dict['workday_mode'] = 'NONE'
        if not row_dict['weekend_mode']: row_dict['weekend_mode'] = 'NONE'
        if not row_dict['duty_count']: row_dict['duty_count'] = 1

        # 处理人员ID转姓名 (fixed_names, exclude_names)
        def ids_to_names(ids_str):
            if not ids_str: return ""
            ids = ids_str.split(',')
            names = [user_map.get(uid, uid) for uid in ids] 
            return ",".join(names)

        row_dict['fixed_names'] = ids_to_names(row_dict.get('fixed_user_ids'))
        row_dict['exclude_names'] = ids_to_names(row_dict.get('exclude_user_ids'))
        
        result.append(row_dict)

    return jsonify({"code": 0, "msg": "", "count": len(result), "data": result})


@bp_schedule.route('/api/config/save', methods=['POST'])
def api_config_save():
    """ 
    保存右侧的排班规则配置 (批量保存) 
    前端传来的 item.shift_id 实际上就是 shift_settings 表的主键 id
    """
    data = request.json
    dept_id = data.get('dept_id')
    configs = data.get('configs', [])

    try:
        # 遍历更新规则字段
        for item in configs:
            target_id = item.get('shift_id') # 这里 shift_id 对应 shift_settings.id
            
            sql = """
                UPDATE shift_settings 
                SET workday_mode=?, weekend_mode=?, duty_count=?, fixed_user_ids=?, exclude_user_ids=?
                WHERE id = ? AND id_department = ?
            """
            modify_db(sql, (
                item.get('workday_mode'), 
                item.get('weekend_mode'), 
                item.get('duty_count'),
                item.get('fixed_user_ids'), 
                item.get('exclude_user_ids'),
                target_id,
                dept_id # 增加 dept_id 校验，防止越权修改
            ))

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


# ======================= 3. 班次定义管理 (增/删/改) =======================

@bp_schedule.route('/api/shift/save', methods=['POST'])
def api_shift_save():
    """ 新增或编辑班次 (基础信息) """
    data = request.json
    try:
        if data.get('id'):
            # 编辑：只更新基础定义字段，保留规则字段不变
            sql = """
                UPDATE shift_settings 
                SET name=?, color=?, start_time=?, end_time=?, is_next_day=?
                WHERE id = ?
            """
            modify_db(sql, (
                data['name'], data['color'], data['start_time'], data['end_time'], 
                int(data['is_next_day']), data['id']
            ))
        else:
            # 新增：插入基础字段，规则字段将使用数据库默认值 (NONE, 1等)
            sql = """
                INSERT INTO shift_settings (name, color, start_time, end_time, is_next_day, id_department)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            modify_db(sql, (
                data['name'], data['color'], data['start_time'], data['end_time'], 
                int(data['is_next_day']), data['id_department']
            ))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


@bp_schedule.route('/api/shift/delete', methods=['POST'])
def api_shift_delete():
    """ 删除班次 """
    data = request.json
    shift_id = data.get('id')
    try:
        # 1. 删除班次设置 (单表)
        modify_db("DELETE FROM shift_settings WHERE id = ?", (shift_id,))
        # 2. 删除对应的轮值顺序 (级联删除)
        modify_db("DELETE FROM schedule_rotation WHERE shift_id = ?", (shift_id,))
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


# ======================= 4. 轮值顺序管理 =======================

@bp_schedule.route('/api/rotation/get', methods=['GET'])
def api_rotation_get():
    """ 获取某班次的轮值人员列表 (按优先级排序) """
    dept_id = request.args.get('dept_id')
    shift_id = request.args.get('shift_id') # 这里的 shift_id 即 shift_settings.id
    
    # 逻辑不变：取出部门所有人，左连接 rotation 表
    sql = """
        SELECT u.id, u.username, r.priority
        FROM user u
        LEFT JOIN schedule_rotation r ON u.id = r.user_id AND r.shift_id = ?
        WHERE u.id_department = ? AND u.staff_flag = 1
        ORDER BY 
            CASE WHEN r.priority IS NULL THEN 1 ELSE 0 END, -- 有排名的在前
            r.priority ASC,
            u.id ASC
    """
    users = query_db(sql, (shift_id, dept_id))
    result = [dict(u) for u in users]
    return jsonify({"success": True, "data": result})


@bp_schedule.route('/api/rotation/save', methods=['POST'])
def api_rotation_save():
    """ 保存轮值顺序 """
    data = request.json
    dept_id = data.get('dept_id')
    shift_id = data.get('shift_id')
    user_ids = data.get('user_ids', []) 
    print(data)
    try:
        # 先删除旧排序，再插入新排序
        modify_db("DELETE FROM schedule_rotation WHERE dept_id=? AND shift_id=?", (dept_id, shift_id))
        
        for index, uid in enumerate(user_ids):
            # priority 从 1 开始
            sql = "INSERT INTO schedule_rotation (dept_id, shift_id, user_id, priority) VALUES (?, ?, ?, ?)"
            modify_db(sql, (dept_id, shift_id, uid, index + 1))
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


# ======================= 5. 节假日/特殊日期管理 (无变动) =======================

@bp_schedule.route('/api/holiday/list', methods=['GET'])
def api_holiday_list():
    """ 获取当前部门设置的所有特殊日期 """
    dept_id = request.args.get('dept_id')
    
    sql = "SELECT exception_date, type, note FROM calendar_exception WHERE dept_id = ?"
    rows = query_db(sql, (dept_id,))
    
    data_map = {}
    for r in rows:
        data_map[r['exception_date']] = {
            "type": r['type'],
            "note": r['note']
        }
        
    return jsonify({"code": 0, "data": data_map})


@bp_schedule.route('/api/holiday/set', methods=['POST'])
def api_holiday_set():
    """ 设置某天为节假日或工作日 """
    data = request.json
    dept_id = data.get('dept_id')
    date_str = data.get('date') 
    h_type = data.get('type')   
    note = data.get('note', '') # 增加备注字段

    try:
        check = query_db("SELECT id FROM calendar_exception WHERE dept_id=? AND exception_date=?", (dept_id, date_str), one=True)
        
        if check:
            modify_db("UPDATE calendar_exception SET type=?, note=? WHERE id=?", (h_type, note, check['id']))
        else:
            modify_db("INSERT INTO calendar_exception (dept_id, exception_date, type, note) VALUES (?, ?, ?, ?)", 
                      (dept_id, date_str, h_type, note))
                      
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


@bp_schedule.route('/api/holiday/delete', methods=['POST'])
def api_holiday_delete():
    """ 清除某天的设置 """
    data = request.json
    dept_id = data.get('dept_id')
    date_str = data.get('date')

    try:
        modify_db("DELETE FROM calendar_exception WHERE dept_id=? AND exception_date=?", (dept_id, date_str))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})