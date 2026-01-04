# deepseekapi.py 负责进行AI处理
import json
from openai import OpenAI
from apps.tools.db import query_db
from datetime import datetime

# DeepSeek 客户端初始化
client = OpenAI(
    api_key="sk-0a9b8a52fef24da59e9214bd7e8bf588",
    base_url="https://api.deepseek.com"
)

def calculate_detailed_metrics(logs):
    """
    针对真实日志样本优化的计算逻辑
    """
    fmt = "%Y-%m-%d %H:%M:%S"
    events = []
    
    for log in logs:
        try:
            # 兼容处理created_at
            dt_val = log.get('created_at')
            ts = datetime.strptime(str(dt_val), fmt) if isinstance(dt_val, str) else dt_val

            events.append({
                "ts": ts,
                "action": log.get('action', ''),
                "details": log.get('details', '') or '',
                "before": int(log.get('prev_status') if log.get('prev_status') is not None else 99),
                "after": int(log.get('curr_status') if log.get('curr_status') is not None else 99)
            })
        except: continue
    
    # 严格按时间排序
    events.sort(key=lambda x: x["ts"])

    t_first_create = None
    t_first_arrival = None
    t_last_finish = None # 完工可能多次（如驳回重修），取最后一次
    
    total_suspend_minutes = 0
    suspend_start_ts = None
    suspend_reasons = []
    rejection_count = 0 # 记录驳回次数，供AI参考

    for ev in events:
        # 1. 首次发起时间 (99 -> 0)
        if ev["before"] == 99 and t_first_create is None:
            t_first_create = ev["ts"]

        # 2. 最早到达时间 (工作人员或委外)
        if ev["action"] in ["工作人员到达", "委外到达"]:
            if t_first_arrival is None:
                t_first_arrival = ev["ts"]

        # 3. 完工时间 (适配：委外完工、完成工单（二维码）)
        # 逻辑：即使被驳回了，我们也记录最后一次申报完工的时间
        if ev["action"] in ["完成工单（二维码）", "完成工单（设备）", "委外完工", "委外完成"]:
            t_last_finish = ev["ts"]

        # 4. 累计挂起逻辑 (状态码 11)
        if ev["after"] == 11:
            suspend_start_ts = ev["ts"]
            if ev["details"]: suspend_reasons.append(ev["details"])
        
        if ev["before"] == 11 and ev["after"] != 11 and suspend_start_ts:
            total_suspend_minutes += (ev["ts"] - suspend_start_ts).total_seconds() / 60
            suspend_start_ts = None
            
        # 5. 特殊处理：记录驳回 (32 -> 12)
        if ev["action"] == "需求科室驳回":
            rejection_count += 1

    def diff_min(a, b):
        return int((b - a).total_seconds() / 60) if a and b else 0

    return {
        "t_create": t_first_create,
        "arrival_minutes": diff_min(t_first_create, t_first_arrival),
        "work_minutes": diff_min(t_first_arrival, t_last_finish),
        "suspend_minutes": int(total_suspend_minutes),
        "suspend_reasons": " | ".join(list(set(suspend_reasons))) if suspend_reasons else "无",
        "rejection_count": rejection_count
    }


def get_ai_suggestion(demand, id_hospital):
    try:
        # 1. 查询任务类型
        # query_db 返回的是字典列表，例如 [{'id': 1, 'task_name': 'xx', ...}, ...]
        task_types = query_db("SELECT id, task_name, description FROM task_type")
        
        # 如果数据库为空，query_db 可能返回空列表，join 不会报错
        if not task_types:
            task_types = []

        task_list_prompt = "\n".join(
            [f"ID:{t['id']} | 任务名称:{t['task_name']} | 描述:{t['description']}" for t in task_types]
        )

        # 2. 查询可受理部门（work_flag=1）
        dept_sql = "SELECT id_department, department_name, description FROM department WHERE id_hospital=? AND work_flag=1"
        departments = query_db(dept_sql, (id_hospital,))

        if not departments:
            departments = []

        dept_list_prompt = "\n".join(
            [f"部门ID:{d['id_department']} |部门名称:{d['department_name']} | 工作职责:{d['description']}" for d in departments]
        )

        categories = "维修、安装、巡检、维护、保养、操作、其它"
        system_prompt = f"""
                    你是一名医院工单智能分类助手。请阅读用户需求，完成以下任务：
                    1. 识别任务类型：从提供的任务库中选择最匹配的 ID。
                    2. 确定受理部门：根据职责描述选择最匹配的部门 ID。
                    3. 分类工作类型：维修/安装/巡检/维护/保养/其它。
                    4. 提取具体地点：从需求描述中提取出具体的物理位置（如：5楼护士站、CT室门口）。如果未提及具体地点，请输出"现场"。

                    用户需求内容: {demand}
                    
                    相关的任务类型库: {task_list_prompt}
                    可受理部门信息: {dept_list_prompt}
                    工作类型范围: {categories}

                    输出要求:
                    - 只输出有效 JSON
                    - JSON 字段必须包含:
                        task_type_id: 任务类型ID
                        work_type: 工作类型
                        work_department: 受理部门ID
                        extracted_location: 提取到的具体地点
                    - 不允许输出解释或多余文字
                    """
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": system_prompt}],
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content
        return json.loads(content) if content else {}

    except Exception as e:
        print("❌ AI 识别失败:", e)
        return {}
    

def analyze_work_order_performance(demand, logs):
    """
    智能工单绩效分析：调用计算方法并交给 AI 进行深度审计
    """
    try:
        # 1. 获取基础计算指标
        m = calculate_detailed_metrics(logs)
        print(m)
        # 2. 获取任务类型库 (用于 AI 匹配 ID)
        task_types = query_db("SELECT id, task_name FROM task_type")
        task_list_str = json.dumps([{"id": t['id'], "n": t['task_name']} for t in task_types], ensure_ascii=False)

        # 3. 判定特殊加分项 (如夜间)
        night_bonus = ""
        if m["t_create"] and (m["t_create"].hour >= 22 or m["t_create"].hour < 6):
            night_bonus = " (该工单为夜间报修，系数应适当上浮 0.2)"

        # 4. 构建 AI Prompt
        system_prompt = f"""
        你是一名医院后勤绩效审计专家。请基于核心事实数据对工单进行量化评分。

        ### 1. 任务背景
        - 用户需求: {demand}
        - 任务库参考 (JSON): {task_list_str}

        ### 2. 核心事实数据 (已由系统精准计算)
        - 到达用时: {m['arrival_minutes'] if m['arrival_minutes'] >=0 else '未知'} 分钟
        - 工作用时: {m['work_minutes'] if m['work_minutes'] >=0 else '未知'} 分钟 (注: 包含挂起在内的总签到时长)
        - 累计挂起时间: {m['suspend_minutes']} 分钟
        - 挂起原因记录: {m['suspend_reasons']}
        {night_bonus}

        ### 3. 审计评分标准
        - [到达评分]: 考核响应。 <15m (+2); 15-30m (+1); 30-60m (0); >60m (-1至-2)。
        - [工作评分]: 考核效率。若“工作用时 - 挂起时间”极短且解决问题，给高分。若无故拖沓给负分。
        - [合理性诊断]: 重点分析“挂起原因”是否支撑“挂起时长”。例如：单纯换灯泡却因“缺件”挂起3天是不合理的。
        - [难度系数]: 基础1.0。高空、脏累、夜间、多部门协作或疑难故障可调高至 1.5-3.0。

        ### 4. 输出要求 (严格 JSON)
        请输出以下 JSON 格式:
        {{
            "final_task_type_id": int,   // 匹配最接近的任务ID
            "task_coefficient": float,   // 建议系数 (1.0 - 10.0)
            "arrival_score": int,        // 到达评分
            "repair_score": int,         // 工作评分
            "reasoning": "string"        // 50~100字左右的审计简报，评价效率及挂起合理性
        }}
        """

        # 5. 调用 DeepSeek API
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": system_prompt}],
            response_format={"type": "json_object"},
            temperature=0.2 # 较低温度保证评分稳定性
        )
        
        # 6. 解析结果并注入原始计算值 (可选，方便调试)
        result = json.loads(response.choices[0].message.content)
        return result

    except Exception as e:
        print(f"❌ AI性能分析异常: {e}")
        return {
            "final_task_type_id": None,
            "task_coefficient": 1.0,
            "arrival_score": 0,
            "repair_score": 0,
            "reasoning": f"分析服务暂时不可用 (错误: {str(e)})"
        }


def recommend_relevant_devices(order_info, candidate_devices):
    """
    order_info: 字典，包含 demand, location, work_content 等
    candidate_devices: 列表，包含本部门的所有设备基础信息
    """
    # 1. 预处理候选设备数据
    simplified_candidates = []
    for d in candidate_devices:
        simplified_candidates.append({
            "id": d['id'],
            "n": d['name'], 
            "m": d.get('model', '') or '无', # 避免 null
            "loc": d.get('install_location', '') or '无'
        })

    # 2. 构建改进后的提示词
    system_prompt = f"""
    你是一名医院设备管理专家。请根据工单描述，从候选列表中找出最可能关联的 3 个设备。

    ### 核心逻辑 (请严格遵守)
    1. **功能匹配 (第一优先级)**: 工单的“描述”或“工作内容”中涉及的设备类型（如空调、电脑、打印机）必须与设备的名称(n)或型号(m)对应。
       - *特例*：如果设备是“系统”级（如“10楼空调系统”、“配电系统”），它通常覆盖该层楼的所有房间（如护士站、病房），应当被视为**高度匹配**，除非位置明显冲突（如工单在1楼，设备在10楼）。
    2. **位置匹配 (辅助验证)**: 
       - 如果工单位置较具体（如“护士站”），而设备位置较宽泛（如“10楼”），只要不冲突，应优先通过功能来判断。
       - 只有当位置出现明显矛盾时（例如工单写“3楼”，设备写“5楼”），才排除该设备。
    3. **关键词提取**: 从工单中提取核心名词（如"Y形过滤器"通常属于水路或空调系统）。

    ### 待分析工单
    - 故障描述: {order_info.get('demand', '无')}
    - 工作内容: {order_info.get('work_content', '无')}
    - 报修位置: {order_info.get('location', '无')}

    ### 候选设备列表 (已按部门筛选)
    {json.dumps(simplified_candidates, ensure_ascii=False)}

    ### 输出要求
    - 返回 JSON 格式: {{ "device_ids": [id1, id2, id3] }}
    - 按可能性降序排列。
    """
    
    print(f"DEBUG PROMPT LEN: {len(system_prompt)}") # 调试用

    try:
        # 3. 调用 DeepSeek API
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": system_prompt}],
            response_format={"type": "json_object"},
            temperature=0.1, 
            max_tokens=200
        )

        content = response.choices[0].message.content
        print(f"AI Response: {content}") # 调试打印结果

        # 4. 解析结果
        if not content:
            return []
            
        result = json.loads(content)
        device_ids = result.get("device_ids", [])
        
        return [int(uid) for uid in device_ids if isinstance(uid, (int, str))][:3]

    except Exception as e:
        print(f"❌ AI 设备匹配失败: {e}")
        # 兜底逻辑：简单的关键词匹配
        try:
            keywords = str(order_info.get('demand', '') + order_info.get('location', ''))
            fallback_ids = []
            for dev in candidate_devices:
                score = 0
                name = dev.get('name', '') or ''
                # 简单名称包含匹配
                if name and any(k in name for k in ['空调', '系统', '水', '电'] if k in keywords):
                    score += 10
                if score > 0:
                    fallback_ids.append({'id': dev['id'], 'score': score})
            fallback_ids.sort(key=lambda x: x['score'], reverse=True)
            return [x['id'] for x in fallback_ids[:3]]
        except:
            return []