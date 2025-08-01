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

#include "node_info_helper.h"

namespace kcal::utils {

NodeInfoHelper::NodeInfoHelper(int worldSize)
{
    infos_.resize(worldSize);
    for (int i = 0; i < worldSize; ++i) {
        infos_[i].nodeId = i;
    }

    nodeInfos_.nodeInfo = infos_.data();
    nodeInfos_.size = infos_.size();
}

}
