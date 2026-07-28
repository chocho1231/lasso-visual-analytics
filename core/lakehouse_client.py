import duckdb

class LassoDataClient:
    #def __init__(self, data_path="my_sample_data.parquet"): 
    def __init__(self, data_path="data/mbpp_798__sum_two_runs.parquet"):
        self.conn = duckdb.connect(database=":memory:", read_only=False)
        self.conn.execute(f"CREATE VIEW observations AS SELECT * FROM read_parquet('{data_path}')")
    
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