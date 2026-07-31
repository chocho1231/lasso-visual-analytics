"""
Copyright (c) 2026, Chair of Software Technology
All rights reserved.
Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
• Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer. 
• Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution. 
• Neither the name of the University Mannheim nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission. 

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import duckdb

class LassoDataClient:
    def __init__(self, 
                 data_path="data/mbpp_798__sum_two_runs.parquet",
                 be_data_path="data/mbpp_798__sum_be_runs.parquet"): # 新增 BE 数据路径
        self.conn = duckdb.connect(database=":memory:", read_only=False)
        
        # 1. core view - va tab
        self.conn.execute(f"CREATE VIEW observations AS SELECT * FROM read_parquet('{data_path}')")
        
        # 2. be tab
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