-- Run once against the CRM database if punch_machine_imports already existed without Tabulator columns.

ALTER TABLE punch_machine_imports
  ADD COLUMN detected_format VARCHAR(80) NULL,
  ADD COLUMN report_year INT NULL,
  ADD COLUMN report_month INT NULL,
  ADD COLUMN statistics_json LONGTEXT NULL;

CREATE TABLE IF NOT EXISTS punch_machine_schedule_days (
  id INT AUTO_INCREMENT PRIMARY KEY,
  import_id INT NOT NULL,
  machine_user_key VARCHAR(80) NOT NULL,
  username VARCHAR(50) NULL,
  work_date DATE NOT NULL,
  code VARCHAR(20) NULL,
  INDEX ix_pmsd_import (import_id),
  INDEX ix_pmsd_user_date (username, work_date),
  CONSTRAINT fk_pmsd_import FOREIGN KEY (import_id) REFERENCES punch_machine_imports(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS punch_machine_exception_days (
  id INT AUTO_INCREMENT PRIMARY KEY,
  import_id INT NOT NULL,
  machine_user_key VARCHAR(80) NOT NULL,
  username VARCHAR(50) NULL,
  work_date DATE NOT NULL,
  late_min INT NULL,
  early_min INT NULL,
  absence_min INT NULL,
  total_min INT NULL,
  raw_json LONGTEXT NULL,
  INDEX ix_pmed_import (import_id),
  INDEX ix_pmed_user_date (username, work_date),
  CONSTRAINT fk_pmed_import FOREIGN KEY (import_id) REFERENCES punch_machine_imports(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
