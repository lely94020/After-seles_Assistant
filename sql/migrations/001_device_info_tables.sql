-- 设备型号信息表
CREATE TABLE IF NOT EXISTS device_model_info (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    model_number VARCHAR(100) UNIQUE NOT NULL COMMENT '设备型号',
    product_series VARCHAR(100) COMMENT '产品系列',
    product_name VARCHAR(255) COMMENT '产品名称',
    category VARCHAR(100) COMMENT '产品类别',
    specifications JSON COMMENT '规格参数',
    wiring_diagram VARCHAR(500) COMMENT '接线图链接',
    firmware_versions JSON COMMENT '固件版本列表',
    knowledge_base_docs JSON COMMENT '关联知识库文档',
    warranty_months INT DEFAULT 24 COMMENT '保修月数',
    status ENUM('active', 'discontinued', 'legacy') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='设备型号信息表';

-- 设备序列号信息表
CREATE TABLE IF NOT EXISTS device_serial_numbers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    serial_number VARCHAR(100) UNIQUE NOT NULL COMMENT '序列号',
    model_number VARCHAR(100) NOT NULL COMMENT '对应型号',
    purchase_date DATE COMMENT '购买日期',
    purchase_channel VARCHAR(255) COMMENT '购买渠道',
    warranty_start_date DATE COMMENT '保修开始日期',
    warranty_end_date DATE COMMENT '保修结束日期',
    status ENUM('active', 'expired', 'out_of_warranty', 'inactive') DEFAULT 'active' COMMENT '保修状态',
    customer_info JSON COMMENT '客户信息',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (model_number) REFERENCES device_model_info(model_number) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='设备序列号信息表';

-- 为常用查询创建索引
CREATE INDEX idx_device_model_number ON device_model_info(model_number);
CREATE INDEX idx_device_serial_number ON device_serial_numbers(serial_number);
CREATE INDEX idx_device_purchase_date ON device_serial_numbers(purchase_date);
CREATE INDEX idx_device_warranty_end ON device_serial_numbers(warranty_end_date);