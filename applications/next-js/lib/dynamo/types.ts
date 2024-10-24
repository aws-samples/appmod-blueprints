export type Menu = {
  title: string;
  path: string;
};

export type Page = {
  id: string;
  title: string;
  handle: string;
  body: string;
  bodySummary: string;
  createdAt: string;
  updatedAt: string;
};

export type Category = {
  path: string;
  categoryId: string;
  title: string;
  description: string;
};

export type Image = {
  url: string;
  altText: string;
  width: number;
  height: number;
};

export type CartProduct = {
  product: Product;
  quantity: number;
  selectedVariant: ProductVariants | undefined;
}

export type ProductOptions = {
  id: string;
  name: string;
  values: string[];
};

export type ProductVariants = {
  id: string;
  title: string;
  price: string;
};

export type Product = {
  id: string;
  name: string;
  description: string;
  inventory: number;
  options: ProductOptions[];
  variants: ProductVariants[];
  price: string;
  images: Image[];
};

export type Cart = {
  id: string;
  products: CartProduct[];
  totalQuantity: number;
  cost: string;
  checkoutUrl: string;
};
