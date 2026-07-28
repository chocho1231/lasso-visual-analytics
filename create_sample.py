import duckdb

# 请确保 'data/full_data.parquet' 是你当前全量数据的实际路径
query = """
    COPY (
        SELECT * FROM 'data/full_data.parquet' 
        LIMIT 10000
    ) TO 'data/sample_data.parquet' (FORMAT PARQUET);
"""

duckdb.execute(query)
print("样本数据 sample_data.parquet 已成功生成！")