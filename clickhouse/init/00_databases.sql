CREATE DATABASE IF NOT EXISTS bronze;
CREATE DATABASE IF NOT EXISTS gold;

CREATE ROLE IF NOT EXISTS bi_reader;
CREATE ROLE IF NOT EXISTS etl_role;

CREATE USER IF NOT EXISTS etl_runner IDENTIFIED WITH sha256_password BY 'etl_runner';
CREATE USER IF NOT EXISTS superset IDENTIFIED WITH sha256_password BY 'superset';

GRANT SELECT ON gold.* TO bi_reader;
GRANT SELECT ON system.tables TO bi_reader;
GRANT SELECT ON system.columns TO bi_reader;

GRANT SELECT, INSERT, ALTER ON bronze.* TO etl_role;
GRANT SELECT, INSERT, ALTER ON gold.* TO etl_role;
GRANT CREATE TEMPORARY TABLE ON *.* TO etl_role;
GRANT POSTGRES ON *.* TO etl_role;

GRANT etl_role TO etl_runner;
GRANT bi_reader TO superset;
