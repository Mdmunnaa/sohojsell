"""
আগে আপলোড হওয়া প্রোডাক্টের ছবি ছোট করা আর thumbnail বানানো।
নতুন আপলোড নিজে থেকেই ছোট হয় (Product.save); এটা শুধু পুরনোগুলোর জন্য।
build.sh প্রতি deploy-এ চালায়; যেগুলোর thumbnail আছে সেগুলো বাদ যায়, তাই পরেরবার দ্রুত শেষ হয়।

    python manage.py optimize_images --limit 300
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from store import images
from store.models import Product


class Command(BaseCommand):
    help = 'পুরনো প্রোডাক্টের ছবি ছোট করে thumbnail বানায়'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=300, help='একবারে সর্বোচ্চ কয়টা প্রোডাক্ট')

    def handle(self, *args, limit, **options):
        pending = (Product.objects.exclude(image='').exclude(image__isnull=True)
                   .filter(Q(thumbnail__isnull=True) | Q(thumbnail='')))
        done = failed = 0
        for product in pending.order_by('-id')[:limit]:
            try:
                main, thumb, size = images.product_versions(product.image)
                if main is None:
                    failed += 1
                    continue
                # আসল ফাইল মুছি না: কাস্টমারের কার্টে পুরনো লিংক থাকতে পারে
                product.image.save(main.name, main, save=False)
                product.thumbnail.save(thumb.name, thumb, save=False)
                Product.objects.filter(pk=product.pk).update(
                    image=product.image.name, thumbnail=product.thumbnail.name,
                    image_width=size[0], image_height=size[1])
                done += 1
            except Exception as exc:     # একটা ছবির সমস্যায় বাকিগুলো থামবে না
                failed += 1
                self.stderr.write(f'#{product.pk}: {exc}')
        self.stdout.write(f'ছবি ছোট করা হলো: {done}টা, পারা যায়নি: {failed}টা')
