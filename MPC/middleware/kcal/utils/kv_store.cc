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

#include "kcal/utils/kv_store.h"

namespace kcal::io {

void MemKVStore::Put(std::string_view key, MpcShare *value)
{
    mapCache_.insert(std::make_pair(key, value));
}

bool MemKVStore::Get(std::string_view key, MpcShare *&value)
{
    auto it = mapCache_.find(static_cast<std::string>(key));
    if (it != mapCache_.end()) {
        value = it->second;
        return true;
    }
    return false;
}

void MemKVStore::Delete(std::string_view key)
{
    auto it = mapCache_.find(static_cast<std::string>(key));
    if (it != mapCache_.end()) {
        delete it->second;
        it->second = nullptr;
    }
}

} // namespace kcal::io
