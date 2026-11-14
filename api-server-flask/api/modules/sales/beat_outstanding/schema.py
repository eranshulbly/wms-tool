# -*- encoding: utf-8 -*-
"""Tables owned by sales.beat_outstanding.

  bo_exec_beat     every beat each executive owns, kept by hand on the Executive Beats
                   page — who appears on Beat Outstanding, and whose dealers go on their
                   cash-discount sheet
  bo_beat_plan     the beats each executive covers on a date, ticked on the Beat
                   Outstanding page

The Tally outstanding report is never stored: the page sends it with each request. Cadila
has one beat (service.BEAT_ALL) and every dealer is on it, so there is no outlet table.
"""

from api.shared.schema_registry import register_table


register_table("bo_beat_plan", """
CREATE TABLE IF NOT EXISTS bo_beat_plan (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    upload_id     BIGINT UNSIGNED NOT NULL DEFAULT 0,
    user_id       VARCHAR(64)  NOT NULL DEFAULT '',
    se_name       VARCHAR(255) NOT NULL,
    plan_date     DATE NOT NULL,
    beat_id       VARCHAR(64)  NOT NULL,
    beat_name     VARCHAR(255) NOT NULL DEFAULT '',
    total_outlets INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_bo_beat_plan_date (company_id, plan_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=111)


register_table("bo_exec_beat", """
CREATE TABLE IF NOT EXISTS bo_exec_beat (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    se_name       VARCHAR(255) NOT NULL,
    beat_name     VARCHAR(255) NOT NULL,
    updated_by    VARCHAR(100) NOT NULL DEFAULT '',
    updated_on    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_bo_exec_beat (company_id, se_name, beat_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=114)
