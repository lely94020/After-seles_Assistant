-- 海康售后技术支持智能助手 - 模拟数据
-- 按照外键依赖顺序插入

-- 角色数据
INSERT INTO roles (id, role_name, description, permissions) VALUES
(1, 'end_user', '终端客户', '{"chat": true, "ticket_create": true, "device_query": true}'),
(2, 'integrator', '系统集成商', '{"chat": true, "ticket_create": true, "device_query": true, "sdk_docs": true}'),
(3, 'distributor', '经销商', '{"chat": true, "ticket_create": true, "device_query": true, "warranty_query": true}'),
(4, 'kb_admin', '知识库管理员', '{"kb_manage": true, "kb_upload": true, "kb_review": true}'),
(5, 'cs_manager', '客服主管', '{"chat_review": true, "quality_monitor": true, "analytics": true, "user_manage": true}'),
(6, 'service_staff', '售后网点人员', '{"ticket_view": true, "ticket_update": true, "ticket_resolve": true}');

-- 用户数据
INSERT INTO users (id, username, password_hash, email, phone, role_id, user_type, company_name) VALUES
(1, 'zhang_wei', '$2b$12$examplehash001', 'zhangwei@example.com', '13800001001', 2, 'integrator', '杭州安盾系统集成有限公司'),
(2, 'li_na', '$2b$12$examplehash002', 'lina@hikdealer.com', '13900002002', 3, 'distributor', '深圳市海安科技有限公司'),
(3, 'wang_fang', '$2b$12$examplehash003', 'wangfang@property.com', '13700003003', 1, 'end_user', '绿城物业管理有限公司'),
(4, 'admin_chen', '$2b$12$examplehash004', 'chen_admin@hikvision.com', '13600004004', 4, 'kb_admin', '海康威视技术支持部'),
(5, 'manager_liu', '$2b$12$examplehash005', 'liu_manager@hikvision.com', '13500005005', 5, 'cs_manager', '海康威视客服中心'),
(6, 'service_zhao', '$2b$12$examplehash006', 'zhao_service@hikvision.com', '13400006006', 6, 'service_staff', '海康威视杭州售后网点');

-- 设备数据
INSERT INTO devices (id, model_number, product_series, product_name, category, specifications, warranty_months, status) VALUES
(1, 'DS-2CD3T86FWDV2', '3系列', '800万全彩网络摄像机', '前端产品-固定摄像机',
 '{"resolution": "3840x2160", "lens": "2.8mm/4mm/6mm", "ir_distance": "50m", "poe": true, "power": "DC12V/PoE", "working_temp": "-30°C~60°C", "protection": "IP67"}', 36, 'active'),
(2, 'DS-7608NI-K2/8P', '76N系列', '8路网络硬盘录像机', '后端产品-NVR',
 '{"channels": 8, "hdd_bays": 2, "max_hdd": "10TB each", "resolution": "up to 8MP", "poe_ports": 8, "network": "RJ45 10/100/1000Mbps", "power": "DC12V"}', 24, 'active'),
(3, 'DS-K1T671M', '门禁系列', '人脸识别门禁一体机', '门禁设备',
 '{"display": "7寸触摸屏", "capacity_face": 20000, "capacity_card": 50000, "recognition_speed": "<0.2s", "working_temp": "-30°C~60°C", "protection": "IP65"}', 24, 'active'),
(4, 'DS-2CD7A87G0', '7系列', '800万智能网络摄像机', '前端产品-固定摄像机',
 '{"resolution": "3840x2160", "ai_features": ["face_capture", "vehicle_detection", "perimeter_protection"], "lens": "2.8-12mm电动变焦", "ir_distance": "80m", "poe": true, "power": "DC12V/PoE/AC24V"}', 36, 'active'),
(5, 'DS-2CD2T47G2-L', '2系列智能', '400万全彩网络摄像机', '前端产品-固定摄像机',
 '{"resolution": "2560x1440", "lens": "2.8mm/4mm", "ir_distance": "30m", "poe": true, "power": "DC12V/PoE", "smart_features": ["human_detection", "line_crossing"]}', 24, 'active');

-- 对话数据
INSERT INTO conversations (id, user_id, title, status, intent_type, key_facts, message_count, resolved_by_ai) VALUES
(1, 1, 'DS-2CD3T86FWDV2 多台设备离线排查', 'resolved', 'fault_diagnosis',
 '{"device_model": "DS-2CD3T86FWDV2", "device_count": 6, "symptom": "全部离线", "network_topology": "POE交换机", "resolved_cause": "POE功率不足"}', 12, true),
(2, 2, 'DS-7608NI-K2 保修查询与报修', 'escalated', 'warranty_service',
 '{"device_model": "DS-7608NI-K2", "serial_number": "DS7608NI20230815001", "warranty_status": "在保", "remaining_months": 8}', 6, false),
(3, 3, '如何在手机上查看监控回放', 'resolved', 'product_inquiry',
 '{"feature": "手机远程回放", "app": "海康互联", "resolved": true}', 4, true);

-- 消息数据
INSERT INTO messages (id, conversation_id, role, content, confidence_score, sources) VALUES
(1, 1, 'user', '我们工厂有6台 DS-2CD3T86FWDV2 摄像机突然全部离线了，NVR上显示网络不可达，怎么回事？', NULL, NULL),
(2, 1, 'assistant', '您好，6台设备同时离线通常与网络环境有关。请确认以下几点：\n1. 这6台摄像机是通过POE交换机供电还是独立电源供电？\n2. 交换机上的端口指示灯是否正常亮起？\n3. 能否从NVR上ping通摄像机的IP地址？', 0.85, NULL),
(3, 1, 'user', '用的是POE交换机供电，端口灯有几个不亮。', NULL, NULL),
(4, 1, 'assistant', '端口灯不亮说明对应的摄像机没有建立网络连接。DS-2CD3T86FWDV2 单台最大功耗约12W（含红外灯），6台需要约72W。请确认您的POE交换机总功率预算是否足够。\n\n**建议方案**：更换为总功率 ≥ 120W 的8口POE交换机（预留余量），推荐型号参见产品手册中的配套交换机列表。\n\n参考文档：[DS-2CD3T86FWDV2 产品手册 - 电源规格](/kb/doc/1)', 0.92, '[{"doc_id": 1, "title": "DS-2CD3T86FWDV2 产品手册"}]');

-- 工单数据
INSERT INTO work_orders (id, order_number, user_id, device_id, conversation_id, order_type, status, fault_description, serial_number, contact_info, assigned_to) VALUES
(1, 'WO-20260609-0001', 2, 2, 2, 'fault_repair', 'assigned',
 'DS-7608NI-K2/8P NVR 开机无画面，电源指示灯亮但HDMI和VGA均无输出，尝试更换显示器无效。',
 'DS7608NI20230815001', '李娜 13900002002', 6);

INSERT INTO work_order_notes (work_order_id, operator_id, content, action_type) VALUES
(1, 6, '已收到工单，预计明天上午上门检查。初步判断可能是主板或显卡故障。', 'note');

-- 知识库文档数据
INSERT INTO kb_documents (id, title, doc_type, product_model, product_series, status, version, chunk_count) VALUES
(1, 'DS-2CD3T86FWDV2 产品手册', 'product_manual', 'DS-2CD3T86FWDV2', '3系列', 'active', 2, 15),
(2, 'POE供电常见问题', 'faq', NULL, NULL, 'active', 1, 5),
(3, 'NVR 开机无画面排查指南', 'troubleshooting', 'DS-7608NI-K2', '76N系列', 'active', 1, 8),
(4, '7系列摄像机智能侦测Pro配置指南', 'product_manual', 'DS-2CD7A87G0', '7系列', 'active', 3, 12),
(5, '海康互联APP远程回放操作指南', 'product_manual', NULL, NULL, 'active', 1, 4);

-- 知识库分块数据（示例）
INSERT INTO kb_chunks (document_id, chunk_index, content, chunk_type, parent_title, token_count) VALUES
(1, 0, 'DS-2CD3T86FWDV2 是海康威视3系列800万全彩网络摄像机，支持PoE供电（IEEE 802.3af），单台最大功耗12W。工作温度-30°C~60°C，防护等级IP67。', 'paragraph', '产品概述', 80),
(1, 1, '| 参数 | 规格 |\n|------|------|\n| 分辨率 | 3840×2160 |\n| 镜头 | 2.8mm/4mm/6mm |\n| 红外距离 | 50m |\n| PoE | 支持 |\n| 供电 | DC12V/PoE |', 'table', '技术规格', 60),
(2, 0, 'Q: POE交换机功率不够怎么办？\nA: 计算所有接入设备的总功耗（含红外灯开启时的最大功耗），选择总功率预算大于总功耗1.5倍的POE交换机。例如6台DS-2CD3T86FWDV2（12W×6=72W），建议选择≥120W的交换机。', 'paragraph', 'POE功率不足', 100),
(3, 0, 'NVR开机无画面排查步骤：\n1. 确认电源适配器输出电压正常（DC12V±5%）\n2. 检查HDMI/VGA线缆是否插紧，尝试更换线缆\n3. 尝试连接不同的显示器\n4. 长按RESET键10秒恢复出厂设置\n5. 如以上步骤均无效，可能是主板故障，需返修', 'step', '排查步骤', 120);