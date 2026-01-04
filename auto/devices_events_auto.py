import random
import calendar
import traceback
from datetime import datetime, timedelta
import db
query_db = db.query_db
execute_transaction = db.execute_transaction
# ================= 时间计算辅助 (保持不变) =================
def add_months(source_dt, months):
    month = source_dt.month - 1 + months
    year = source_dt.year + month // 12
    month = month % 12 + 1
    day = min(source_dt.day, calendar.monthrange(year, month)[1])
    return source_dt.replace(year=year, month=month, day=day)

def get_next_datetime_object(dt, val, unit):
    if unit == 'hour':
        return dt + timedelta(hours=val)
    elif unit == 'day':
        return dt + timedelta(days=val)
    elif unit == 'month':
        return add_months(dt, val)
    return dt

# ================= 阶段 1: 准备工单相关的所有 SQL =================
def prepare_work_order_ops(event):
    """
    只负责生成 SQL 列表，不执行数据库写入
    :return: (operations_list, logic_success)
    """
    ops = [] # 存放 (sql, args)
    
    try:
        print(f"[*] 准备处理事件 ID: {event['id']} | 类型: {event.get('event_type')}")

        # 1. 查询设备信息 (读操作，直接用 query_db)
        device = query_db("SELECT * FROM facility_object WHERE id = ?", (event['device_id'],), one=True)
        if not device:
            print(f"    [!] 错误: 设备 ID {event['device_id']} 未找到，跳过。")
            return [], False

        # 2. 逻辑计算 (科室、部门、类型等)
        use_dept_name = device.get('use_department_name')
        use_dept_id = device.get('use_department_id')
        mgmt_dept_name = device.get('department_name')
        mgmt_dept_id = device.get('id_department')

        if not use_dept_id or str(use_dept_id) == "0":
            start_dept_name = mgmt_dept_name
            start_dept_id = mgmt_dept_id
        else:
            start_dept_name = use_dept_name
            start_dept_id = use_dept_id

        handle_dept_name = mgmt_dept_name
        handle_dept_id = mgmt_dept_id
        
        TASK_TYPE_MAP = {"巡检": 120, "操作": 121, "维护": 122, "保养": 123, "检验": 124, "其它": 125}
        event_type = event.get('event_type', "其它")
        task_type_id = TASK_TYPE_MAP.get(event_type, 125)
        
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        rand_code = str(random.randint(0, 99)).zfill(2)
        work_id = f"D-{timestamp}-{event['device_id']}-{rand_code}"
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        location_str = device.get('name', '')
        demand_str = f"对{device.get('name')}进行{event_type},具体工作内容: {event.get('content')}。"
        detail_log = f"【系统创建工单】对{device.get('name')}进行{event_type},工作内容: {event.get('content')}，受理部门：{handle_dept_name}"
        device_log = f"【{event_type}】系统创建工单，对{device.get('name')}进行{event_type},工作内容: {event.get('content')}，受理部门：{handle_dept_name}"

        # -------------------------------------------------
        # 构建 SQL 操作列表 (Append 模式)
        # -------------------------------------------------

        # Op 1: 插入工单主表
        sql_order = """
            INSERT INTO work_orders (
                id, source, demand, location, contact_phone, report_photo,
                created_at, status, task_type, work_type, 
                work_department, work_department_name,
                id_created_department, created_department_name,
                id_created_hospital, with_device
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        args_order = (
            work_id, "系统生成", demand_str, location_str, "系统自动发布", "", created_at, 
            0, task_type_id, event_type,
            handle_dept_id, handle_dept_name,
            start_dept_id, start_dept_name,
            device.get('id_hospital'), event['device_id']
        )
        ops.append((sql_order, args_order))

        # Op 2: 插入工单日志 (work_order_logs)
        sql_log = """
            INSERT INTO work_order_logs 
            (work_id, action, operator_name, prev_status, curr_status, details, staff, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        args_log = (work_id, "首次发起（自动）", "系统", 99, 0, detail_log, "系统", created_at)
        ops.append((sql_log, args_log))

        # Op 3: 插入设备日志 (devices_log)
        sql_dev_log = """
            INSERT INTO devices_log (
                device_id, occur_time, 
                hospital_name, hospital_id,
                start_department_name, start_department_id,
                handle_department_name, handle_department_id,
                related_work_order, work_content, staff, type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        args_dev_log = (
            device['id'], created_at,
            device.get('hospital_name'), device.get('id_hospital'),
            start_dept_name, start_dept_id,
            handle_dept_name, handle_dept_id,
            work_id, device_log, "", event_type
        )
        ops.append((sql_dev_log, args_dev_log))

        print(f"    [+] 工单 SQL 准备就绪: {work_id}")
        return ops, True

    except Exception as e:
        print(f"    [!] 生成过程准备异常: {e}")
        traceback.print_exc()
        return [], False

# ================= 阶段 2: 准备更新周期的 SQL =================
def prepare_schedule_ops(event):
    """
    计算时间并返回更新或删除的 SQL 操作
    :return: (operations_list, logic_success)
    """
    ops = []
    try:
        event_id = event['id']
        cycle_val = event['cycle_val']
        cycle_unit = event['cycle_unit']
        
        if cycle_val and cycle_val > 0 and cycle_unit:
            # 1. 解析基准时间
            current_run_time_str = event['next_run_time']
            dt_base = datetime.now()
            if current_run_time_str:
                try:
                    dt_base = datetime.strptime(current_run_time_str, '%Y-%m-%d %H:%M:%S')
                except:
                    pass # Fallback to now

            # 2. 追赶逻辑 (计算出未来时间)
            now = datetime.now()
            next_dt = get_next_datetime_object(dt_base, cycle_val, cycle_unit)
            
            # 防止死循环：最多追赶 50 次，或者你可以只加一次
            loop_guard = 0
            while next_dt <= now and loop_guard < 50:
                next_dt = get_next_datetime_object(next_dt, cycle_val, cycle_unit)
                loop_guard += 1

            new_next_time = next_dt.strftime('%Y-%m-%d %H:%M:%S')
            print(f"    [>] 计划更新下次时间: {new_next_time}")
            
            # 准备 UPDATE SQL
            sql_update = "UPDATE device_events SET next_run_time = ? WHERE id = ?"
            ops.append((sql_update, (new_next_time, event_id)))
            
        else:
            # 无周期则删除
            print(f"    [x] 计划删除无周期事件 ID: {event_id}")
            sql_delete = "DELETE FROM device_events WHERE id = ?"
            ops.append((sql_delete, (event_id,)))

        return ops, True

    except Exception as e:
        print(f"    [!] 周期计算异常: {e}")
        return [], False

# ================= 主流程：扫描与原子性执行 =================
def run_device_event_scan():
    print(f"--- [扫描开始] {datetime.now().strftime('%H:%M:%S')} ---")
    
    try:
        # 1. 获取任务 (读操作)
        # 这里的 query_db 来自你的 auto.db 模块，它会自动开关连接
        sql_scan = """
            SELECT * FROM device_events 
            WHERE next_run_time IS NOT NULL 
            AND next_run_time <= datetime('now', 'localtime')
        """
        events = query_db(sql_scan)
        
        if not events:
            print("    (无到期事件)")
            print("--- [扫描结束] ---\n")
            return

        print(f"    发现 {len(events)} 个到期事件")

        # 2. 遍历处理
        for event in events:
            # Step A: 获取工单相关的 SQL 操作列表
            wo_ops, wo_success = prepare_work_order_ops(event)
            if not wo_success:
                print(f"    [-] 跳过事件 {event['id']} (数据准备失败)")
                continue

            # Step B: 获取周期更新的 SQL 操作列表
            sch_ops, sch_success = prepare_schedule_ops(event)
            if not sch_success:
                print(f"    [-] 跳过事件 {event['id']} (周期计算失败)")
                continue

            # Step C: 合并操作，原子执行
            # 将两个列表合并：[插入工单, 插入日志, 插入设备日志, 更新下一次时间]
            combined_ops = wo_ops + sch_ops
            
            # 调用 execute_transaction 一次性提交所有更改
            # 如果中间任何一句 SQL 失败，execute_transaction 内部会自动回滚
            success, msg = execute_transaction(combined_ops)

            if success:
                print(f"    [√] 事务提交成功: 事件 {event['id']} 已处理。\n")
            else:
                print(f"    [!] 事务提交失败: {msg}\n")

    except Exception as e:
        print(f"全局扫描异常: {e}")
        traceback.print_exc()
    
    print("--- [扫描结束] ---\n")

