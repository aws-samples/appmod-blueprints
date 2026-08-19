'use client';

import { Dialog, Transition } from '@headlessui/react';
import { BookmarkIcon } from '@heroicons/react/24/outline';
import Price from 'components/price';
import { DEFAULT_OPTION } from 'lib/constants';
import type {Wishlist} from 'lib/dynamo/types';
import { createUrl } from 'lib/utils';
import Image from 'next/image';
import Link from 'next/link';
import { Fragment, useEffect, useRef, useState } from 'react';
import CloseWishlist from './close-wishlist';
import { DeleteItemButton } from './remove-from-wishlist';
import OpenWishlist from './open-wishlist';

type MerchandiseSearchParams = {
  [key: string]: string;
};

export default function WishlistModal({ wishlist }: { wishlist: Wishlist | undefined }) {
  const [isOpen, setIsOpen] = useState(false);
  const quantityRef = useRef(wishlist?.products.length);
  const openWishlist = () => setIsOpen(true);
  const closeWishlist = () => setIsOpen(false);

  return (
    <>
      <button aria-label="Open wishlist" onClick={openWishlist}>
        <OpenWishlist quantity={wishlist?.products.length} />
      </button>
      <Transition show={isOpen}>
        <Dialog onClose={closeWishlist} className="relative z-50">
          <Transition.Child
            as={Fragment}
            enter="transition-all ease-in-out duration-300"
            enterFrom="opacity-0 backdrop-blur-none"
            enterTo="opacity-100 backdrop-blur-[.5px]"
            leave="transition-all ease-in-out duration-200"
            leaveFrom="opacity-100 backdrop-blur-[.5px]"
            leaveTo="opacity-0 backdrop-blur-none"
          >
            <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
          </Transition.Child>
          <Transition.Child
            as={Fragment}
            enter="transition-all ease-in-out duration-300"
            enterFrom="translate-x-full"
            enterTo="translate-x-0"
            leave="transition-all ease-in-out duration-200"
            leaveFrom="translate-x-0"
            leaveTo="translate-x-full"
          >
            <Dialog.Panel className="fixed bottom-0 right-0 top-0 flex h-full w-full flex-col border-l border-neutral-200 bg-white/80 p-6 text-black backdrop-blur-xl md:w-[390px] dark:border-neutral-700 dark:bg-black/80 dark:text-white">
              <div className="flex items-center justify-between">
                <p className="text-lg font-semibold">My Wishlist</p>

                <button aria-label="Close wishlist" onClick={closeWishlist}>
                  <CloseWishlist />
                </button>
              </div>

              {!wishlist || wishlist.products.length === 0 ? (
                <div className="mt-20 flex w-full flex-col items-center justify-center overflow-hidden">
                  <BookmarkIcon className="h-16" />
                  <p className="mt-6 text-center text-2xl font-bold">Your wishlist is empty.</p>
                </div>
              ) : (
                <div className="flex h-full flex-col justify-between overflow-hidden p-1">
                  <ul className="flex-grow overflow-auto py-4">
                    {wishlist.products.map((item, i) => {
                      const merchandiseSearchParams = {} as MerchandiseSearchParams;

                      item.product.options.forEach(({ name }) => {
                        if (name !== DEFAULT_OPTION) {
                          merchandiseSearchParams[name.toLowerCase()] = name;
                        }
                      });

                      const merchandiseUrl = createUrl(
                        `/product/${item.product.id}`,
                        new URLSearchParams(merchandiseSearchParams)
                      );

                      return (
                        <li
                          key={i}
                          className="flex w-full flex-col border-b border-neutral-300 dark:border-neutral-700"
                        >
                          <div className="relative flex w-full flex-row justify-between px-1 py-4">
                            <div className="absolute z-40 -mt-2 ml-[55px]">
                              <DeleteItemButton item={item} />
                            </div>
                            <Link
                              href={merchandiseUrl}
                              onClick={closeWishlist}
                              className="z-30 flex flex-row space-x-4"
                            >
                              <div className="relative h-16 w-16 cursor-pointer overflow-hidden rounded-md border border-neutral-300 bg-neutral-300 dark:border-neutral-700 dark:bg-neutral-900 dark:hover:bg-neutral-800">
                                <Image
                                  className="h-full w-full object-cover"
                                  // Served by the rust microservice via the shared ingress domain,
                                  // not this app's own server -- skip next/image's optimizer.
                                  unoptimized
                                  width={64}
                                  height={64}
                                  alt={item.product.images[0]!.altText || item.product.name}
                                  src={item.product.images[0]!.url}
                                />
                              </div>

                              <div className="flex flex-1 flex-col text-base">
                                <span className="leading-tight">{item.product.name}</span>
                                {item.product.name !== DEFAULT_OPTION ? (
                                  <p className="text-sm text-neutral-500 dark:text-neutral-400">
                                    {item.product.name}
                                  </p>
                                ) : null}
                              </div>
                            </Link>
                            <div className="flex h-16 flex-col justify-between">
                              <Price
                                className="flex justify-end space-y-2 text-right text-sm"
                                amount={item.selectedVariant?.price || item.product.price}
                                currencyCode={'USD'}
                              />
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </Dialog.Panel>
          </Transition.Child>
        </Dialog>
      </Transition>
    </>
  );
}