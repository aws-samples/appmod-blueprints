import Footer from 'components/layout/footer';
import { Carousel } from 'components/carousel';
import { ThreeItemGrid } from 'components/grid/three-items';

export default async function HomePage() {
  return (
    <>
      <ThreeItemGrid />
      <Carousel />
      <Footer />
    </>
  );
}
