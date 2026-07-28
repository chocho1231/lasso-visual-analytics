from core.lakehouse_client import LassoDataClient
import orjson

def run_test():
    # 1. 初始化客户端 (这里假设你稍后会把数据链接过来)
    # 注意：运行前，确保你有一个 lakehouse 数据库的路径！
    # 如果你本地还没建好，可以先用你 analysis.ipynb 里的临时测试路径
    client = LassoDataClient()
    
    # 2. obtain data for problem_id="mbpp_798__sum"
    print("Fetching SRM data...")
    records = client.get_srm_matrix(problem_id="mbpp_798__sum")
    
    # 3. print the results in a readable format
    if records:
        print(f"Success! Fetched {len(records)} rows. Here are the first 2:")
        print(orjson.dumps(records[:2], option=orjson.OPT_INDENT_2).decode('utf-8'))
    else:
        print("No data found or database is empty.")

if __name__ == "__main__":
    run_test()