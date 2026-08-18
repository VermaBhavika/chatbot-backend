-- ============================================================
-- schema.sql
--
-- Run this ONCE against your MySQL database to create all tables.
-- Beginner note: run it like this from your terminal:
--   mysql -u root -p reputracker < schema.sql
-- (replace "reputracker" with whatever MYSQL_DATABASE you set in .env)
--
-- If the database itself doesn't exist yet, create it first:
--   CREATE DATABASE reputracker;
-- ============================================================

-- One row per company. This almost never changes month to month.
CREATE TABLE IF NOT EXISTS companies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    public_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    created_at DATETIME,
    updated_at DATETIME
);

-- One row per company PER MONTH. This grows every month.
CREATE TABLE IF NOT EXISTS monthly_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    company_id INT NOT NULL,
    execution_id INT,
    public_id VARCHAR(64) UNIQUE,
    month_year VARCHAR(7) NOT NULL,   -- format: "2026-05"
    status VARCHAR(20),
    total_score DECIMAL(5,2),
    overall_score_percentage INT,
    total_modules INT,
    total_data_sources INT,
    created_at DATETIME,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE KEY uniq_company_month (company_id, month_year)
);

-- One row PER MODULE per monthly report.
-- Since there are 5 modules (pov, awareness, engagement, perception,
-- employee_sentiment), each monthly_report will have 5 rows here,
-- all sharing the same monthly_report_id.
CREATE TABLE IF NOT EXISTS modules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    monthly_report_id INT NOT NULL,
    module_name VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    final_score DECIMAL(5,2),
    max_possible_score DECIMAL(5,2),
    score_percentage INT,
    public_id VARCHAR(64),
    FOREIGN KEY (monthly_report_id) REFERENCES monthly_reports(id)
);

-- One row per module, holding the qualitative text
-- (this is what gets embedded into Chroma for semantic search).
CREATE TABLE IF NOT EXISTS module_insights (
    id INT AUTO_INCREMENT PRIMARY KEY,
    module_id INT NOT NULL,
    tagline TEXT,
    pros JSON,
    cons JSON,
    recommendations JSON,
    FOREIGN KEY (module_id) REFERENCES modules(id)
);

-- One row per monthly report, holding the overall narrative summary.
CREATE TABLE IF NOT EXISTS report_summaries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    monthly_report_id INT NOT NULL,
    overall_summary TEXT,
    total_modules_analyzed INT,
    FOREIGN KEY (monthly_report_id) REFERENCES monthly_reports(id)
);

-- Helpful indexes for the queries tools.py will run often.
CREATE INDEX idx_modules_report ON modules(monthly_report_id);
CREATE INDEX idx_modules_name ON modules(module_name);
CREATE INDEX idx_reports_month ON monthly_reports(month_year);
