-- 示例设备型号数据
INSERT INTO device_model_info (
    model_number,
    product_series,
    product_name,
    category,
    specifications,
    wiring_diagram,
    firmware_versions,
    knowledge_base_docs,
    warranty_months,
    status
) VALUES
(
    'DS-2CD2T86G1-I8',
    'EasyIP 3.0',
    '筒型网络摄像机',
    '网络摄像机',
    '{"sensor": "1/2.7\" CMOS", "resolution": "8MP", "ir_distance": "30m", "power_supply": "DC12V/POE", "operating_temperature": "-30°C ~ +60°C", "protection_level": "IP67", "smart_detection": ["human_body_detection", "vehicle_detection"]} ',
    'http://example.com/wiring/ds-2cd2t86g1-i8.pdf',
    '["V5.7.0", "V5.7.1", "V5.7.2", "V5.7.3"]',
    '["doc_camera_setup", "doc_troubleshooting", "doc_smart_features"]',
    36,
    'active'
),
(
    'DS-2CD2143G2-I',
    'EasyIP 3.0',
    '筒型网络摄像机',
    '网络摄像机',
    '{"sensor": "1/3\" CMOS", "resolution": "4MP", "ir_distance": "30m", "power_supply": "DC12V/POE", "operating_temperature": "-30°C ~ +60°C", "protection_level": "IP67", "smart_detection": ["human_body_detection"]} ',
    'http://example.com/wiring/ds-2cd2143g2-i.pdf',
    '["V5.6.8", "V5.6.9", "V5.6.10"]',
    '["doc_camera_setup", "doc_troubleshooting"]',
    24,
    'active'
),
(
    'DS-7616NI-K2/16P',
    'NVR系列',
    '16路POE网络硬盘录像机',
    '网络硬盘录像机',
    '{"channel_input": 16, "hdd_bay": 2, "max_resolution": "8MP", "network_interface": "RJ45", "power_supply": "AC220V", "po_support": 120} ',
    'http://example.com/wiring/ds-7616ni-k2-16p.pdf',
    '["V4.3.52", "V4.3.53", "V4.3.54"]',
    '["doc_nvr_setup", "doc_network_config", "doc_backup_recovery"]',
    36,
    'active'
),
(
    'DS-A7100EF-MP',
    '门禁产品',
    '人脸识别一体机',
    '智能门禁',
    '{"display_size": "7 inch", "camera_type": "IR dual vision camera", "recognition_distance": "0.3-0.8m", "supported_features": ["face_recognition", "card_swipe", "password"], "power_supply": "DC12V"} ',
    'http://example.com/wiring/ds-a7100ef-mp.pdf',
    '["V3.0.1", "V3.0.2", "V3.0.3"]',
    '["doc_access_control_setup", "doc_face_recognition_config"]',
    24,
    'active'
);

-- 示例设备序列号数据
INSERT INTO device_serial_numbers (
    serial_number,
    model_number,
    purchase_date,
    purchase_channel,
    warranty_start_date,
    warranty_end_date,
    customer_info,
    status
) VALUES
(
    'C202301000001',
    'DS-2CD2T86G1-I8',
    '2023-01-15',
    '授权经销商-北京科技有限公司',
    '2023-01-15',
    '2026-01-15',
    '{"company": "某物业公司", "contact_person": "李经理", "contact_phone": "13800138001", "address": "北京市朝阳区XX街道XX号"}',
    'active'
),
(
    'C202302000001',
    'DS-2CD2143G2-I',
    '2023-02-20',
    '官方直销',
    '2023-02-20',
    '2025-02-20',
    '{"company": "某酒店管理公司", "contact_person": "王经理", "contact_phone": "13800138002", "address": "上海市浦东新区XX路XX号"}',
    'active'
),
(
    'C202212000001',
    'DS-7616NI-K2/16P',
    '2022-12-05',
    '授权经销商-广州安防有限公司',
    '2022-12-05',
    '2025-12-05',
    '{"company": "某商场管理公司", "contact_person": "张主管", "contact_phone": "13800138003", "address": "广州市天河区XX大道XX号"}',
    'active'
),
(
    'C202303000001',
    'DS-A7100EF-MP',
    '2023-03-10',
    '授权经销商-深圳电子有限公司',
    '2023-03-10',
    '2025-03-10',
    '{"company": "某写字楼物业", "contact_person": "刘主任", "contact_phone": "13800138004", "address": "深圳市南山区XX科技园XX栋"}',
    'active'
),
(
    'C202111000001',
    'DS-2CD2T86G1-I8',
    '2021-11-10',
    '授权经销商-成都科技有限公司',
    '2021-11-10',
    '2024-11-10',
    '{"company": "某学校", "contact_person": "陈老师", "contact_phone": "13800138005", "address": "成都市锦江区XX路XX号"}',
    'out_of_warranty'
);

-- 添加外键约束（如果尚未存在）
ALTER TABLE device_serial_numbers ADD CONSTRAINT fk_device_serial_model
FOREIGN KEY (model_number) REFERENCES device_model_info(model_number) ON DELETE CASCADE;