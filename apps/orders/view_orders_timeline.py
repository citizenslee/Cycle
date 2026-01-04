# orders_list.py 工单列表页面
from flask import render_template
from apps.tools.auth import login_required, permission_required
# 引入数据库工具
from apps.tools.db import query_db
from .route import bp_orders
from datetime import datetime

def format_duration(seconds):
    if seconds is None: return None
    if seconds < 60: return "1分钟内"
    
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    
    parts = []
    if days > 0: parts.append(f"{days}天")
    if hours > 0: parts.append(f"{hours}小时")
    if minutes > 0: parts.append(f"{minutes}分")
    return "".join(parts)

from flask import render_template, request
from apps.tools.db import query_db
from .route import bp_orders
from datetime import datetime

def format_duration(seconds):
    """将秒数转换为人性化时间字符串"""
    if seconds is None: return None
    if seconds < 60: return "1分钟内"
    
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    
    parts = []
    if days > 0: parts.append(f"{days}天")
    if hours > 0: parts.append(f"{hours}小时")
    if minutes > 0: parts.append(f"{minutes}分")
    return "".join(parts)

@bp_orders.route('/flow/<work_id>')
def order_flow_page(work_id):
    # 1. 首先从主表 work_orders 查询该工单的图片数据
    # 假设主表的字段名是 report_photo 和 finish_photo
    main_sql = "SELECT report_photo, finish_photo FROM work_orders WHERE id = ?"
    main_order = query_db(main_sql, (work_id,), one=True)
    
    # 2. 获取流转日志
    sql = "SELECT * FROM work_order_logs WHERE work_id = ? ORDER BY created_at ASC"
    logs = query_db(sql, (work_id,))
    
    processed_logs = []
    for i, log in enumerate(logs):
        current_log = dict(log)
        action = current_log.get('action', '')
        
        # 3. 计算节点间的耗时
        if i < len(logs) - 1:
            try:
                t1 = datetime.strptime(current_log['created_at'], '%Y-%m-%d %H:%M:%S')
                t2 = datetime.strptime(logs[i+1]['created_at'], '%Y-%m-%d %H:%M:%S')
                diff_seconds = (t2 - t1).total_seconds()
                current_log['duration_text'] = format_duration(diff_seconds)
            except Exception:
                current_log['duration_text'] = None
        
        # 4. 动作类型分类 (决定颜色和图标)
        if any(x in action for x in ['发起', '初始']): 
            current_log['type'] = 'start'
        elif any(x in action for x in ['派单', '转单', '指派']): 
            current_log['type'] = 'dispatch'
        elif any(x in action for x in ['到达', '委外开始', '开始维修']): 
            current_log['type'] = 'process'
        elif any(x in action for x in ['驳回', '挂起', '暂停', '需重修']): 
            current_log['type'] = 'warn'
        elif '委外' in action: 
            current_log['type'] = 'outsource'
        elif any(x in action for x in ['完成', '完工', '通过', '闭环']): 
            current_log['type'] = 'finish'
        elif any(x in action for x in ['评价', '核验', '核价', '验收']): 
            current_log['type'] = 'audit'
        else:
            current_log['type'] = 'default'

        # 5. 图片处理逻辑：从主表 main_order 中提取并挂载到 log 节点
        current_log['display_photos'] = []
        current_log['photo_folder'] = ""

        if main_order:
            # 报修图片：挂载在“发起”动作节点
            if current_log['type'] == 'start' and main_order.get('report_photo'):
                # 兼容多种分隔符 丨 ; ,
                raw_report = main_order['report_photo'].replace('丨', ',').replace(';', ',')
                current_log['display_photos'] = [p.strip() for p in raw_report.split(',') if p.strip()]
                current_log['photo_folder'] = "report"
            
            # 完工图片：挂载在“完成/完工”动作节点
            elif current_log['type'] == 'finish' and main_order.get('finish_photo'):
                raw_finish = main_order['finish_photo'].replace(';', ',')
                # 提取文件名（防止数据库存了带路径的字符串）
                current_log['display_photos'] = [p.split('/')[-1].strip() for p in raw_finish.split(',') if p.strip()]
                current_log['photo_folder'] = "finish"

        processed_logs.append(current_log)

    # 打印调试，确认 display_photos 是否有值
    # print(processed_logs) 

    return render_template('orders/order_flow.html', logs=processed_logs, work_id=work_id)