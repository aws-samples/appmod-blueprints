import { getCart } from 'lib/dynamo';
import { cookies } from 'next/headers';
import CartModal from './modal';

export default async function Cart() {
  const cartId = (await cookies()).get('cartId')?.value;
  let cart;

  if (cartId) {
    const cartResult = await getCart(cartId);
    if (!(cartResult instanceof Error)) {
      cart = cartResult;
    }
  }

  return <CartModal cart={cart} />;
}
