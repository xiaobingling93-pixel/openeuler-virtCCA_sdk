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

#include "kcal/utils/io.h"

#include <cstring>
#include <memory>

namespace kcal::io {

// ===========================
//   DataHelper impl
// ===========================

int DataHelper::BuildDgString(const std::vector<std::string> &strings, DG_String **dg)
{
    auto *dgString = new (std::nothrow) DG_String[strings.size()];
    if (dgString == nullptr) {
        return DG_ERR_MALLOC_FAIL;
    }
    for (size_t i = 0; i < strings.size(); ++i) {
        dgString[i].str = strdup(strings[i].c_str());
        dgString[i].size = strings[i].size() + 1;
    }
    *dg = dgString;
    return DG_SUCCESS;
}

void DataHelper::ReleaseDgPairList(DG_PairList *pairList)
{
    if (pairList) {
        for (size_t i = 0; i < pairList->size; i++) {
            if (pairList->dgPair[i].key) {
                delete[] pairList->dgPair[i].key->str;
                delete pairList->dgPair[i].key;
            };
            if (pairList->dgPair[i].value) {
                delete[] pairList->dgPair[i].value->str;
                delete pairList->dgPair[i].value;
            };
        }
        delete[] pairList->dgPair;
        pairList = nullptr;
    }
}

void DataHelper::ReleaseOutput(DG_TeeOutput **output)
{
    if (output == nullptr || *output == nullptr) {
        return;
    }
    if ((*output)->dataType == MPC_STRING && (*output)->data.strings != nullptr) {
        for (size_t i = 0; i < (*output)->size; ++i) {
            delete[] (*output)->data.strings[i].str;
        }
        delete[] (*output)->data.strings;
    } else if ((*output)->dataType == MPC_DOUBLE && (*output)->data.doubleNumbers != nullptr) {
        delete[] (*output)->data.doubleNumbers;
    } else if ((*output)->dataType == MPC_INT && (*output)->data.u64Numbers != nullptr) {
        delete[] (*output)->data.u64Numbers;
    }
    delete *output;
    *output = nullptr;
}

void DataHelper::ReleaseMpcShare(DG_MpcShare **share)
{
    if (share == nullptr || *share == nullptr) {
        return;
    }

    if ((*share)->dataShare == nullptr || (*share)->size == 0) {
        delete (*share);
        return;
    }
    for (unsigned long i = 0; i < (*share)->size; i++) {
        if ((*share)->dataShare[i].shares != nullptr) {
            delete[] (*share)->dataShare[i].shares;
        }
    }
    delete[] (*share)->dataShare;
    delete (*share);
    *share = nullptr;
}

// ===========================
//   KcalMpcShare impl
// ===========================

KcalMpcShare::~KcalMpcShare()
{
    if (share_) {
        DataHelper::ReleaseMpcShare(&share_);
    }
}

// ===========================
//   KcalMpcShareSet impl
// ===========================

KcalMpcShareSet::~KcalMpcShareSet()
{
    if (shareSet_) {
        if (shareSet_->shareSet) {
            delete[] shareSet_->shareSet;
        }
        delete shareSet_;
    }
}

KcalMpcShareSet::KcalMpcShareSet(const std::vector<std::shared_ptr<KcalMpcShare>> &shares)
{
    shareSet_ = new (std::nothrow) DG_MpcShareSet();
    shareSet_->size = shares.size();

    auto shareDatas = std::make_unique<DG_MpcShare[]>(shareSet_->size);
    shareSet_->shareSet = shareDatas.release();

    for (size_t i = 0; i < shares.size(); ++i) {
        shareSet_->shareSet[i] = *shares[i]->Get();
    }
}

KcalMpcShareSet KcalMpcShareSet::Create(const std::vector<KcalMpcShare *> &shares)
{
    KcalMpcShareSet shareSet{};

    shareSet.shareSet_ = new (std::nothrow) DG_MpcShareSet();
    shareSet.shareSet_->size = shares.size();

    auto shareDatas = std::make_unique<DG_MpcShare[]>(shareSet.shareSet_->size);
    shareSet.shareSet_->shareSet = shareDatas.release();

    for (size_t i = 0; i < shares.size(); ++i) {
        shareSet.shareSet_->shareSet[i] = *shares[i]->Get();
    }
    return shareSet;
}

// ===========================
//   KcalInput impl
// ===========================

void KcalInput::Fill(const std::vector<std::string> &data)
{
    DG_String *strings = nullptr;
    DataHelper::BuildDgString(data, &strings);

    input_ = new (std::nothrow) DG_TeeInput();
    input_->data.strings = strings;
    input_->size = static_cast<int>(data.size());
    input_->dataType = MPC_STRING;
}

KcalInput *KcalInput::Create()
{
    std::unique_ptr<DG_TeeInput> teeInput = std::make_unique<DG_TeeInput>();
    std::unique_ptr<KcalInput> input = std::make_unique<KcalInput>(teeInput.release());
    return input.release();
}

KcalPairList *KcalPairList::Create()
{
    std::unique_ptr<DG_PairList> pairList = std::make_unique<DG_PairList>();
    std::unique_ptr<KcalPairList> input = std::make_unique<KcalPairList>(pairList.release());
    return input.release();
}
} // namespace kcal::io
