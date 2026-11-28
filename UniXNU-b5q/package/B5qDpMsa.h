/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung dp_catalog_v420.c257..313 and pinned kernel lib/math/rational.c.
 * rational_best_approximation Copyright (C) 2009 emlix GmbH, Oskar Schirmer;
 * Copyright (C) 2019 Trent Piepho. See reports/p5-link-source.json. */
#pragma once
#include "B5qDpTu.h"
namespace B5qDp { namespace MsaOriginal {
static inline void rational_best_approximation(
	unsigned long given_numerator, unsigned long given_denominator,
	unsigned long max_numerator, unsigned long max_denominator,
	unsigned long *best_numerator, unsigned long *best_denominator)
{
	/* n/d is the starting rational, which is continually
	 * decreased each iteration using the Euclidean algorithm.
	 *
	 * dp is the value of d from the prior iteration.
	 *
	 * n2/d2, n1/d1, and n0/d0 are our successively more accurate
	 * approximations of the rational.  They are, respectively,
	 * the current, previous, and two prior iterations of it.
	 *
	 * a is current term of the continued fraction.
	 */
	unsigned long n, d, n0, d0, n1, d1, n2, d2;
	n = given_numerator;
	d = given_denominator;
	n0 = d1 = 0;
	n1 = d0 = 1;

	for (;;) {
		unsigned long dp, a;

		if (d == 0)
			break;
		/* Find next term in continued fraction, 'a', via
		 * Euclidean algorithm.
		 */
		dp = d;
		a = n / d;
		d = n % d;
		n = dp;

		/* Calculate the current rational approximation (aka
		 * convergent), n2/d2, using the term just found and
		 * the two prior approximations.
		 */
		n2 = n0 + a * n1;
		d2 = d0 + a * d1;

		/* If the current convergent exceeds the maxes, then
		 * return either the previous convergent or the
		 * largest semi-convergent, the final term of which is
		 * found below as 't'.
		 */
		if ((n2 > max_numerator) || (d2 > max_denominator)) {
			unsigned long t = UINT64_MAX;

			if (d1)
				t = (max_denominator - d0) / d1;
			if (n1)
				t = t < (max_numerator - n0) / n1 ? t : (max_numerator - n0) / n1;

			/* This tests if the semi-convergent is closer than the previous
			 * convergent.  If d1 is zero there is no previous convergent as this
			 * is the 1st iteration, so always choose the semi-convergent.
			 */
			if (!d1 || 2u * t > a || (2u * t == a && d0 * dp > d1 * d)) {
				n1 = n0 + t * n1;
				d1 = d0 + t * d1;
			}
			break;
		}
		n0 = n1;
		n1 = n2;
		d0 = d1;
		d1 = d2;
	}
	*best_numerator = n1;
	*best_denominator = d1;
}
}
struct Msa {
 uint32_t mvid=0,nvid=0;
 bool calculate(uint32_t pixelKHz,unsigned rate){
  mvid=nvid=0;if(pixelKHz<10000||pixelKHz>675000||(rate!=6&&rate!=10&&rate!=20&&rate!=30))return false;
  unsigned long num=0,den=0;
  MsaOriginal::rational_best_approximation(rate*27000ul*10,pixelKHz,65535,65535,&den,&num);
  if(!num||!den)return false;mvid=uint32_t(num)*10;nvid=uint32_t(den);
  if(nvid<0x8000){
   using namespace TuOriginal;
   auto scale=drm_fixp_from_fraction(0x8000,nvid);
   auto value=drm_fixp_mul(scale,drm_fixp_from_fraction(mvid,1));
   mvid=uint32_t(drm_fixp2int(value));nvid=0x8000;
  }
  return mvid&&mvid<0x1000000&&nvid>=0x8000&&nvid<=65535;
 }
};
}
