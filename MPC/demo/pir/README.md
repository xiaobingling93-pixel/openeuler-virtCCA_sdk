## 前置条件
需安装kcal包

## 编译
```
cd src
rm build && mkdir build
cmake -B build
cd build
make
```

## 如何运行示例
1. 在终端中切换到当前目录， 执行`bash server.sh` 作为`server`端，
2. 另起一个终端，并切换到当前目录， 执行`bash client.sh` 作为`client`端，
3. 在`server`端，等待脚本输出`finish offlineCalculate` 后，输入回车键，
4. 然后，在`client`端，输入回车键，
5. 等待2秒钟，脚本运行结束, 会输出结果文件`out-*.csv`。

## 结果分析
1. `data` 目录存放测试数据, `client.csv`中存放`key`， `server.csv`中存放`key` 和 `valule`，
2. 在结果文件`output-*.csv`中，保存了从服务端查询到的`value` 。
