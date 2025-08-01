/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
 * virtCCA_sdk is licensed under the Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *     http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
 * PURPOSE.
 * See the Mulan PSL v2 for more details.
 */

#ifndef NODE_INFO_HELPER_H
#define NODE_INFO_HELPER_H

#include <vector>
#include "kcal/api/kcal_api.h"

namespace kcal::utils {

class NodeInfoHelper {
public:
    explicit NodeInfoHelper(int worldSize);

    ~NodeInfoHelper() = default;

    NodeInfoHelper(const NodeInfoHelper &) = delete;
    NodeInfoHelper &operator=(const NodeInfoHelper &) = delete;

    TeeNodeInfos *Get() { return &nodeInfos_; }

private:
    TeeNodeInfos nodeInfos_;
    std::vector<TeeNodeInfo> infos_;
};

}

#endif // NODE_INFO_HELPER_H
