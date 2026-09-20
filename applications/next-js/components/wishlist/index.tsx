import { getWishlist } from "lib/dynamo";
import { cookies } from "next/headers";
import WishlistModal from "./modal";

export default async function Wishlist() {
  const wishlistId = (await cookies()).get("wishlistId")?.value;
  let wishlist;

  if (wishlistId) {
    wishlist = await getWishlist(wishlistId);
  }

  return <WishlistModal wishlist={wishlist} />;
}
