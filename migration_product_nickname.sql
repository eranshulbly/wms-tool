-- ============================================================
-- Product Nickname Migration
-- Run once against the target database.
-- ============================================================

-- Add nickname column to product table
-- If a nickname is set it will be used instead of description
-- on the supply sheet PDF headers.
ALTER TABLE product
    ADD COLUMN nickname VARCHAR(200) DEFAULT NULL
    AFTER description;
