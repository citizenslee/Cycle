# 引入必要的库
from datetime import datetime
from apps.tools.db import modify_db

def record_order_flow(work_id, action, operator, curr_status, prev_status=None, staff=None, details=""):
    """
    通用工单流转记录函数
    :param work_id: 工单编号
    :param action: 动作名称 (如: "用户报修", "维修工接单")
    :param operator: 操作人姓名或手机号
    :param curr_status: 操作后的状态 (int)
    :param prev_status: 操作前的状态 (int, 创建时可为 None)
    :param details: 详细说明 (如: AI识别出的分类，或维修工填写的备注)
    """
    try:
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        sql = """
            INSERT INTO work_order_logs 
            (work_id, action, operator_name, prev_status, curr_status, details, staff, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        args = (work_id, action, operator, prev_status, curr_status, details, staff, created_at)
        modify_db(sql, args)
        
    except Exception as e:
        # 记录日志失败不应影响主业务流程，建议只打印错误
        print(f"Error recording order flow: {e}")