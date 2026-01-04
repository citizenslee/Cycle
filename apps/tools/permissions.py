# permissions.py 获取登录用户信息
from flask import session
from apps.tools.db import query_db

# 定义角色等级，数值越大权限越高
# 建议在全项目中统一使用此处的定义，不要在其他文件中重复定义
ROLE_LEVELS = {
    'SA': 100, # 超级管理员
    'GA': 90,  # 集团管理员
    'HP': 55,  # 院长
    'HA': 50,  # 医院管理员
    'DH': 30,  # 科长
    'DA': 25,  # 科室管理员
    'PA': 20,  # 采购管理员
    'SE': 10,  # 受理工程师
    'ST': 10   # 普通员工
}

ROLE_NAMES = {
    'SA': '超级管理员',
    'GA': '集团管理员',
    'HP': '院长',
    'HA': '医院管理员',
    'DH': '科长',
    'DA': '科室管理员',
    'PA': '采购管理员',
    'SE': '受理工程师',
    'ST': '普通员工'
}
# ============================================
# 公共辅助函数
# ============================================
def get_user_role_name(role_str):
    """
    解析多角色字符串，返回最高等级角色的中文名称
    例如: "SE,DA" -> "科室管理员" (因为DA等级高于SE)
    """
    if not role_str:
        return "普通员工"
    
    roles = [r.strip() for r in role_str.split(',') if r.strip()]
    if not roles:
        return "普通员工"
    
    # 按照等级从高到低排序，取第一个
    # 使用 ROLE_LEVELS.get(r, 0) 获取等级，默认0
    sorted_roles = sorted(roles, key=lambda r: ROLE_LEVELS.get(r, 0), reverse=True)
    
    highest_role_code = sorted_roles[0]
    return ROLE_NAMES.get(highest_role_code, highest_role_code)

def get_user_max_level(role_str):
    """
    解析用户角色字符串 (如 "DA,SE") 并返回最高权限等级数值
    :param role_str: 数据库存储的角色字符串
    :return: int (最高等级)
    """
    if not role_str:
        return 0
    # 分割字符串并去除空白
    roles = [r.strip() for r in role_str.split(',') if r.strip()]
    if not roles:
        return 0
    # 映射等级，未定义的角色默认为 0
    levels = [ROLE_LEVELS.get(r, 0) for r in roles]
    return max(levels)


def get_current_user_info():
    """
    获取当前登录用户的完整信息。
    结合 Session (基础信息) 和 Database (实时状态，如科室属性)。
    
    :return: dict (用户信息) or None (未登录)
    """
    
    # 1. 基础 Session 校验
    user_id = session.get("user_id")
    if not user_id:
        return None

    # 获取角色字符串
    role_str = session.get("role", "")

    # 2. 组装基础信息字典
    # 🔥 在这里直接计算 current_level 并放入字典
    user_info = {
        "id": user_id,
        "username": session.get("username"),
        "role": role_str,
        "current_level": get_user_max_level(role_str),  # <--- 新增字段：当前最高权限等级
        "id_hospital": session.get("id_hospital"),
        "hospital_name": session.get("hospital_name", ""),
        "id_department": session.get("id_department"),
        "department_name": session.get("department_name", ""),
        "work_flag": 0,           # 0:普通/临床, 1:职能
        "is_functional": False    # 是否职能科室的快捷布尔值
    }

    # 3. 查库获取实时的科室属性 (work_flag)
    # Session 里的数据可能是旧的，或者 Session 里根本没存 work_flag
    if user_info["id_department"]:
        sql = "SELECT work_flag FROM department WHERE id_department = ?"
        dept_data = query_db(sql, (user_info["id_department"],), one=True)
        
        if dept_data:
            work_flag = dept_data.get('work_flag', 0)
            user_info["work_flag"] = work_flag
            user_info["is_functional"] = (work_flag == 1)                        

    return user_info