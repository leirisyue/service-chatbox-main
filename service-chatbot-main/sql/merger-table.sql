-- ============================================
-- CONFIGURATION SECTION
-- ============================================

-- 1. Database connection configuration
SET @DB1_NAME = 'database1';
SET @DB2_NAME = 'database2';

-- 2. Table names in DB1
SET @TABLE1_NAME = 'MD_Material_SAP';
SET @TABLE2_NAME = 'ListMaterialsBOQ';

-- 3. Column mapping configuration
-- Format: (source_table, source_column, unified_column_name)
-- This maps different column names from two tables to a common name
CREATE TEMPORARY TABLE IF NOT EXISTS column_mapping_config (
    table_name VARCHAR(50),
    source_column VARCHAR(100),
    unified_column VARCHAR(100)
);

-- Clear existing config
DELETE FROM column_mapping_config;

-- Insert mapping configuration
-- Example: Map columnA from table1 and columnX from table2 to unified_column_A
INSERT INTO column_mapping_config (table_name, source_column, unified_column) VALUES
(@TABLE1_NAME, 'columnA_table1', 'unified_column_A'),
(@TABLE1_NAME, 'columnB_table1', 'unified_column_B'),
(@TABLE1_NAME, 'columnC_table1', 'unified_column_C'),
(@TABLE2_NAME, 'columnA_table2', 'unified_column_A'),
(@TABLE2_NAME, 'columnD_table2', 'unified_column_D'),
(@TABLE2_NAME, 'columnE_table2', 'unified_column_E');

-- 4. Columns to select (based on unified column names)
-- Specify which unified columns you want to include in the final view
SET @COLUMNS_TO_SELECT = 'unified_column_A, unified_column_B, unified_column_C';

-- ============================================
-- VIEW CREATION SCRIPT
-- ============================================

-- Use DB2 as the target database
USE `@DB2_NAME`;

-- Drop view if exists
DROP VIEW IF EXISTS `VIEWS`.`merged_tables_view`;

-- Create the view with dynamic column selection
CREATE VIEW `VIEWS`.`merged_tables_view` AS
WITH 
-- Get column mapping for table1
table1_mapping AS (
    SELECT source_column, unified_column
    FROM column_mapping_config
    WHERE table_name = @TABLE1_NAME
    AND FIND_IN_SET(unified_column, REPLACE(@COLUMNS_TO_SELECT, ' ', ''))
),
-- Get column mapping for table2
table2_mapping AS (
    SELECT source_column, unified_column
    FROM column_mapping_config
    WHERE table_name = @TABLE2_NAME
    AND FIND_IN_SET(unified_column, REPLACE(@COLUMNS_TO_SELECT, ' ', ''))
),
-- Build dynamic SELECT statement for table1
table1_columns AS (
    SELECT GROUP_CONCAT(
        CONCAT('t1.`', source_column, '` AS `', unified_column, '`')
        ORDER BY FIELD(unified_column, REPLACE(@COLUMNS_TO_SELECT, ' ', ''))
    ) AS select_clause
    FROM table1_mapping
),
-- Build dynamic SELECT statement for table2
table2_columns AS (
    SELECT GROUP_CONCAT(
        CONCAT('t2.`', source_column, '` AS `', unified_column, '`')
        ORDER BY FIELD(unified_column, REPLACE(@COLUMNS_TO_SELECT, ' ', ''))
    ) AS select_clause
    FROM table2_mapping
)
-- Execute dynamic SQL
SELECT * FROM (
    -- First table
    SELECT 
        @sql1 := CONCAT('SELECT ', (SELECT select_clause FROM table1_columns), 
                        ' FROM `', @DB1_NAME, '`.`', @TABLE1_NAME, '` t1') AS dynamic_sql
    UNION ALL
    -- Second table
    SELECT 
        @sql2 := CONCAT('SELECT ', (SELECT select_clause FROM table2_columns), 
                        ' FROM `', @DB1_NAME, '`.`', @TABLE2_NAME, '` t2') AS dynamic_sql
) AS sql_statements;

-- ============================================
-- EXECUTION SECTION
-- ============================================

-- Prepare and execute the dynamic SQL
SET @final_sql = CONCAT(
    'CREATE OR REPLACE VIEW `VIEWS`.`merged_tables_view` AS ',
    @sql1, ' UNION ALL ', @sql2
);

-- Execute the dynamic SQL
PREPARE stmt FROM @final_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ============================================
-- VERIFICATION SECTION
-- ============================================

-- Display the created view structure
SHOW CREATE VIEW `VIEWS`.`merged_tables_view`;

-- Select sample data from the view (first 10 rows)
SELECT * FROM `VIEWS`.`merged_tables_view` LIMIT 10;

-- ============================================
-- CLEANUP (optional)
-- ============================================

-- Drop temporary configuration table
DROP TEMPORARY TABLE IF EXISTS column_mapping_config;