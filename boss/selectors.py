"""所有 UI 元素选择器集中在此文件。

重要:Boss直聘版本更新会频繁改变控件属性,导致选择器失效。
校准方法:
    1. 手机打开 Boss直聘到目标页面;
    2. 运行 `python tools/dump_ui.py`(会保存 hierarchy.xml 与截图);
    3. 用 dump 出来的 resource-id / text / content-desc 回填下面对应的选择器。

每个选择器都是可直接传给 uiautomator2 的关键字字典,例如 d(**HOME["recommend_tab"])。
"""

# ---------- 首页 / 推荐列表 ----------
# 已用真机 dump 校准(APK 14.160 / versionCode 1416010,
# Android 12 / Redmi K30i 5G / 1080x2400,2026-09-22)。
# 注意:底部导航"职位"Tab 才是入口;"推荐"是职位页顶部的子 Tab(推荐/最新/附近)。
HOME = {
    # 底部导航"职位"Tab(点击后进入职位列表页)
    "job_nav": {"text": "职位"},
    # 职位页顶部"推荐"子 Tab(可能已默认选中而不出现,存在时才点)
    "recommend_tab": {"text": "推荐"},
    # 推荐流中的单个职位卡片容器
    "job_card": {"resourceId": "com.hpbr.bosszhipin:id/view_job_card"},
    # 卡片内的职位标题
    "job_card_title": {"resourceId": "com.hpbr.bosszhipin:id/tv_position_name"},
    # 卡片内的薪资
    "job_card_salary": {"resourceId": "com.hpbr.bosszhipin:id/tv_salary_statue"},
    # 卡片内的公司名
    "job_card_company": {"resourceId": "com.hpbr.bosszhipin:id/tv_company_name"},
}

# ---------- 职位详情 ----------
# 已用真机 dump 校准(BossJobPagerActivity,2026-09-21)。
DETAIL = {
    "title": {"resourceId": "com.hpbr.bosszhipin:id/tv_job_name"},
    "salary": {"resourceId": "com.hpbr.bosszhipin:id/tv_job_salary"},
    # "立即沟通"按钮(核心投递动作),Button + clickable
    "communicate_btn": {"resourceId": "com.hpbr.bosszhipin:id/btn_chat"},
    # 招聘者姓名
    "boss_name": {"resourceId": "com.hpbr.bosszhipin:id/tv_boss_name"},
    # 沟通后可能弹出的"附件简历请求"对话框(招聘者索要简历)。
    # 同一 resource-id 也会出现在聊天中的"交换微信"卡片里，但卡片按钮
    # 在未触发时是 enabled=false；限定 enabled=True，避免误判/误点。
    "resume_agree_btn": {
        "resourceId": "com.hpbr.bosszhipin:id/tv_dialog_btn_right",
        "enabled": True,
    },
    "resume_reject_btn": {
        "resourceId": "com.hpbr.bosszhipin:id/tv_dialog_btn_left",
        "enabled": True,
    },
    # 兼容旧字段
    "confirm_send_resume": {"text": "发送简历"},
    "continue_chat": {"textContains": "继续"},
    "close_popup": {"description": "关闭"},
}

# ---------- 会话 / 聊天 ----------
# 已用真机 dump 校准(ChatRoomActivity,2026-09-21)。
CHAT = {
    # 会话标题/副标题仅作为本地去重指纹的上下文，不是服务端 conversationId。
    "conversation_title": {"resourceId": "com.hpbr.bosszhipin:id/tv_title"},
    # 当前 APK 显示为“公司 · 职位”（例如“梦虎网络 · ceo”）。
    "conversation_subtitle": {"resourceId": "com.hpbr.bosszhipin:id/tv_sub_title"},
    # 聊天输入框(hint=回复消息)
    "input": {"resourceId": "com.hpbr.bosszhipin:id/editText_with_scrollbar"},
    # 发送按钮无 resource-id:输入文字后出现在输入行最右侧的可点击 ImageView,
    # 由 chat.py 按位置动态定位(见 ChatPage._find_send_button)。
    # 空输入时该位置是 mMoreIcon(+号),故必须先输入文字再定位发送键。
    "more_icon": {"resourceId": "com.hpbr.bosszhipin:id/mMoreIcon"},
    # 判断已进入会话页的标志
    "chat_flag": {"resourceId": "com.hpbr.bosszhipin:id/editText_with_scrollbar"},
}

# 全局弹窗关闭按钮。刻意保守:只匹配明确的关闭图标(content-desc=关闭),
# 不用"取消/跳过"等泛文字,避免在会话页等场景误点造成副作用。
GLOBAL_POPUP_CLOSE = [
    {"description": "关闭"},
    {"description": "close"},
]
