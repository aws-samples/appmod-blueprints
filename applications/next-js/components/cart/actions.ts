'use server';

import { TAGS } from 'lib/constants';
import { addToCart, createCart, getCart, removeFromCart, updateCart } from 'lib/dynamo';
import { revalidateTag } from 'next/cache';
import { cookies } from 'next/headers';
import { CartProduct, Product, ProductVariants } from '../../lib/dynamo/types';

export async function addItem(prevState: any, cartItem: CartProduct) {
  let cartId = cookies().get('cartId')?.value;
  let cart;

  if (cartId) {
    cart = await getCart(cartId);
  }

  if (!cartId || !cart) {
    cart = await createCart();
    cartId = cart.id;
    cookies().set('cartId', cartId);
  }

  if (!cartItem) {
    return 'Missing product variant ID';
  }

  try {
    await addToCart(cartId, cartItem);
    revalidateTag(TAGS.cart);
  } catch (e) {
    return 'Error adding item to cart';
  }
}

export async function removeItem(prevState: any, productId: string) {
  const cartId = cookies().get('cartId')?.value;

  if (!cartId) {
    return 'Missing cart ID';
  }

  try {
    await removeFromCart(cartId, productId);
    revalidateTag(TAGS.cart);
  } catch (e) {
    return 'Error removing item from cart';
  }
}

export async function updateItemQuantity(prevState: any, cartItem: CartProduct) {
  const cartId = cookies().get('cartId')?.value;

  if (!cartId) {
    return 'Missing cart ID';
  }

  try {
    if (cartItem.quantity === 0) {
      await removeFromCart(cartId, cartItem.product.id);
      revalidateTag(TAGS.cart);
      return;
    }

    await updateCart(cartItem);
    revalidateTag(TAGS.cart);
  } catch (e) {
    return 'Error updating item quantity';
  }
}
