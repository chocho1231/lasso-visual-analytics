import duckdb

class LassoDataClient:
    def __init__(self, 
                 data_path="data/mbpp_798__sum_two_runs.parquet",
                 be_data_path="data/mbpp_798__sum_be_runs.parquet"): # 新增 BE 数据路径
        self.conn = duckdb.connect(database=":memory:", read_only=False)
        
        # 1. 注册核心视图 (用于 SRM 和 Diff 视图)
        self.conn.execute(f"CREATE VIEW observations AS SELECT * FROM read_parquet('{data_path}')")
        
        # 2. 注册 BE 专属视图 (用于 Behavioral Evolution 视图，解决审阅者的问题 1)
        self.conn.execute(f"CREATE VIEW be_observations AS SELECT * FROM read_parquet('{be_data_path}')")
    
    def get_srm_matrix(self, problem_id: str):
        query = f"""
            WITH test_sequences AS (
                SELECT test_id, step_id, implementation_id, output
                FROM observations
                WHERE problem_id = '{problem_id}'
            )
            PIVOT test_sequences
            ON implementation_id
            USING FIRST(output)
            GROUP BY test_id, step_id
            ORDER BY test_id, step_id
        """
        records = self.conn.execute(query).fetch_arrow_table().to_pylist() 
        return records