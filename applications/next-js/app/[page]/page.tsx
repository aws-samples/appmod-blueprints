import Prose from 'components/prose';
import { getPage } from 'lib/dynamo';
import { notFound } from 'next/navigation';

export default async function Page({ params }: { params: { page: string } }) {
  const page = await getPage(params.page);

  if (!page || page instanceof Error) return notFound();

  return <></>;
}
