#pragma once

#include <cstdlib>
#include <locale.h>
#include <new>
#if defined(__APPLE__)
#include <xlocale.h>
#endif

namespace mslc {

// Keep strtod's rounding, range and suffix handling without consulting or
// changing the embedding application's process/thread locale. POSIX locale
// APIs also work with C++17 libc++ versions lacking floating from_chars.
inline double parseFloatLiteral(const char* text) {
	struct NumericLocale {
		locale_t value = newlocale(LC_NUMERIC_MASK, "C", nullptr);
		NumericLocale() { if (!value) throw std::bad_alloc(); }
		~NumericLocale() { freelocale(value); }
	};
	static const NumericLocale locale;
	return strtod_l(text, nullptr, locale.value);
}

} // namespace mslc
