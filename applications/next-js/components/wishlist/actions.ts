'use server';

import { TAGS } from 'lib/constants';
import { addToWishlist, createWishlist, getWishlist, removeFromWishlist } from 'lib/dynamo';
import { revalidateTag } from 'next/cache';
import { cookies } from 'next/headers';
import { CartProduct, Product, Wishlist } from '../../lib/dynamo/types';

export async function addWishlistItem(prevState: any, wishlistItem: CartProduct) {
  let wishlistId = (await cookies()).get('wishlistId')?.value;
  let wishlist;

  if (wishlistId) {
    wishlist = await getWishlist(wishlistId);
  }

  if (!wishlistId || !wishlist || wishlist instanceof Error) {
    const wishlistResult = await createWishlist();
    if (wishlistResult instanceof Error) {
      return 'Error creating wishlist';
    }
    wishlist = wishlistResult;
    wishlistId = wishlist.id;
    (await cookies()).set('wishlistId', wishlistId);
  }

  if (!wishlistItem) {
    return 'Missing product variant ID';
  }

  try {
    const result = await addToWishlist(wishlistId, wishlistItem);
    if (result instanceof Error) {
      return 'Error adding item to wishlist';
    }
    revalidateTag(TAGS.wishlist);
  } catch (e) {
    return 'Error adding item to wishlist';
  }
}

export async function removeWishlistItem(prevState: any, productId: string) {
  const wishlistId = (await cookies()).get('wishlistId')?.value;

  if (!wishlistId) {
    return 'Missing wishlist ID';
  }

  try {
    const result = await removeFromWishlist(wishlistId, productId);
    if (result instanceof Error) {
      return 'Error removing item from wishlist';
    }
    revalidateTag(TAGS.wishlist);
  } catch (e) {
    return 'Error removing item from wishlist';
  }
}
