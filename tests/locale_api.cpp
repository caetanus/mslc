#include "mslc/mslc.h"
#include "lexer.h"
#include "numeric_locale.h"

#include <clocale>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <locale>
#include <string>
#include <vector>

#define CHECK(condition) do { if (!(condition)) { std::cerr << "line " << __LINE__ << ": " #condition "\n"; std::exit(1); } } while (0)

struct Output {
	std::vector<uint8_t> spirv;
	std::string reflection;
};

static Output translate(const std::string& source) {
	uint8_t* bytes = nullptr;
	size_t size = 0;
	char* reflection = nullptr;
	char* error = nullptr;
	const int result = mslc_translate(source.data(), source.size(), nullptr, &bytes, &size, &reflection, &error);
	if (error) std::cerr << error << '\n';
	CHECK(result == 0 && bytes && reflection);
	Output output{{bytes, bytes + size}, reflection};
	mslc_free(bytes);
	mslc_free(reflection);
	mslc_free(error);
	return output;
}

int main(int argc, char** argv) {
	CHECK(argc == 2);
	std::ifstream input(argv[1]);
	CHECK(input.good());
	const std::string source{std::istreambuf_iterator<char>(input), {}};
	CHECK(std::setlocale(LC_ALL, "C"));
	const Output baseline = translate(source);
	// Include suffixes and range endpoints: the C-locale
	// strtod result is the compatibility contract, including under/overflow.
	const char* literals[] = {"0.333", "1.5e-3", "0.5f", "0.5h", "0.5F", "0.5H",
		"1e-320", "1e-999", "1e999"};
	std::vector<double> expected;
	for (const char* literal: literals) expected.push_back(std::strtod(literal, nullptr));
	CHECK(std::setlocale(LC_ALL, ""));
	CHECK(std::strcmp(std::localeconv()->decimal_point, ",") == 0);
	const std::string hostLocale = std::setlocale(LC_ALL, nullptr);
	std::locale::global(std::locale(""));
	for (size_t i = 0; i < expected.size(); ++i) {
		const auto tokens = mslc::tokenize(literals[i]);
		CHECK(tokens.front().kind == mslc::TokenKind::FloatLiteral);
		CHECK(tokens.front().floatValue == expected[i]);
	}
	// Hex floats are not tokenized by this branch, but the conversion helper
	// must retain strtod semantics for them too.
	CHECK(mslc::parseFloatLiteral("0x1.8p1") == 3.0);
	CHECK(mslc::parseFloatLiteral("0x1p-1074") == std::ldexp(1.0, -1074));
	const Output actual = translate(source);
	CHECK(actual.spirv == baseline.spirv);
	CHECK(actual.reflection == baseline.reflection);
	CHECK(actual.reflection.find("\"lod_min\": 0.333000004") != std::string::npos);
	CHECK(hostLocale == std::setlocale(LC_ALL, nullptr));
	// A changed constant must be observable by this comparison.
	std::string changed = source;
	changed.replace(changed.find("float2(0.333"), std::strlen("float2(0.333"), "float2(0.334");
	CHECK(translate(changed).spirv != baseline.spirv);
}
