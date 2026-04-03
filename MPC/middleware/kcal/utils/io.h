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

#ifndef KCAL_MIDDLEWARE_IO_H
#define KCAL_MIDDLEWARE_IO_H

#include <memory>
#include <string>
#include <vector>

#include "kcal/api/kcal_api.h"

namespace kcal::io {

class DataHelper {
public:
    static int BuildDgString(const std::vector<std::string> &strings, DG_String **dg);

    static void ReleaseOutput(DG_TeeOutput **output);
    static void ReleaseMpcShare(DG_MpcShare **share);
    static void ReleaseDgPairList(DG_PairList *pairList);
};

class MpcShare {
public:
    MpcShare() = default;
    explicit MpcShare(DG_MpcShare *share) : share_(share) {}
    ~MpcShare();

    void Set(DG_MpcShare *share) { share_ = share; }
    DG_MpcShare *&Get() { return share_; }
    DG_MpcShare *Get() const { return share_; }

    unsigned long Size() { return share_->size; }
    DG_ShareType Type() { return share_->shareType; }

private:
    DG_MpcShare *share_ = nullptr; // manage memory release
};

class MpcShareSet {
public:
    MpcShareSet() = default;
    ~MpcShareSet();

    DG_MpcShareSet *Get() { return shareSet_; }
    DG_MpcShareSet *Get() const { return shareSet_; }

    static MpcShareSet Create(const std::vector<MpcShare *> &shares);

private:
    // data reference, not manage memory release
    DG_MpcShareSet *shareSet_;
};

class Input {
public:
    Input() = default;
    explicit Input(DG_TeeInput *input) : input_(input) {}
    ~Input() { DataHelper::ReleaseOutput(&input_); }

    void Set(DG_TeeInput *input) { input_ = input; }
    DG_TeeInput *Get() { return input_; }
    DG_TeeInput *Get() const { return input_; }
    DG_TeeInput **GetSecondaryPointer() { return &input_; }
    void Reset(DG_TeeOutput *output);

    bool Valid() const { return input_ != nullptr; }

    void Fill(const std::vector<std::string> &data);

    int Size() { return input_->size; }

private:
    DG_TeeInput *input_ = nullptr; // manage memory release
};

using Output = Input;

class KcalPairList {
public:
    KcalPairList() = default;
    explicit KcalPairList(DG_PairList *pairList) : pairList_(pairList){};
    ~KcalPairList() { DataHelper::ReleaseDgPairList(pairList_); };
    static KcalPairList *Create();
    DG_PairList *Get() { return pairList_; };
    DG_PairList **GetSecondaryPointer() { return &pairList_; };

private:
    DG_PairList *pairList_ = nullptr;
};

} // namespace kcal::io

#endif // KCAL_MIDDLEWARE_IO_H
