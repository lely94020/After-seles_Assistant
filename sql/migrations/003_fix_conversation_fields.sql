-- 003_fix_conversation_fields.sql
-- 修复 conversations 表：intent_type → intent，status ENUM 补 timeout，添加 step_index/closed_at

-- 1. intent_type 重命名为 intent（与 ORM 模型一致）
ALTER TABLE conversations CHANGE COLUMN intent_type intent VARCHAR(50);

-- 2. status ENUM 补充 timeout 值
ALTER TABLE conversations MODIFY COLUMN status ENUM('active', 'resolved', 'escalated', 'timeout', 'closed') DEFAULT 'active';

-- 3. 添加 ORM 模型中存在但 schema 缺失的列
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS step_index INT DEFAULT 0 AFTER key_facts;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS closed_at DATETIME DEFAULT NULL AFTER updated_at;
