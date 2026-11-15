#pragma once

#include "ast.h"

#include <cstdint>
#include <vector>

namespace mslc {

// How Metal lays types out in memory, shared by the buffer layout in sema and the sizeof
// the parser folds, so the two cannot disagree.

// Where a member sits in a Metal struct, and how far an array of the struct
// steps. Metal puts a float3 at the next multiple of 16 even though it holds
// 12, and steps 16 too, so a float after it starts at 16 rather than 12.
// indium's own lighting test relies on that: the host side declares
// normalMatrix as "float normalMatrix[3][4]", a 176-byte struct whose matrix
// has 16-byte columns.
struct VectorLayout {
	uint32_t size;
	uint32_t alignment;
};

uint32_t storageBytesOf(ScalarKind kind);
VectorLayout vectorLayoutFor(uint32_t scalarBytes, uint32_t components);
VectorLayout packedVectorLayoutFor(uint32_t scalarBytes, uint32_t components);
VectorLayout matrixLayoutFor(uint32_t scalarBytes, uint32_t columns, uint32_t rows);
uint32_t alignTo(uint32_t offset, uint32_t alignment);
VectorLayout elementLayout(const Type& type);
std::vector<uint32_t> arrayStrides(const Type& type);
VectorLayout memberLayout(const Type& type);

}
