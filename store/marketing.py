"""
SEO পাতা: প্রতিটা ফিচার আর ব্যবসার ধরনের আলাদা পাতা, বাংলা (/features/<slug>/, /for/<slug>/) আর ইংরেজি (/en/...)।

প্রতিটা পাতা একটা খোঁজার কথার জন্য (যেমন "ই-কমার্স ওয়েবসাইট তৈরি", "pos software bangladesh")। লেখা শুধু যা সত্যিই
সফটওয়্যারে আছে তা-ই — হোমপেজের দাবির সাথে মিলিয়ে। নতুন পাতা = এখানে একটা dict; টেমপ্লেট store/marketing/page.html,
sitemap আর llms.txt নিজে থেকে নেয়। ছবি: static/landing/<image>.webp (ছোট সংস্করণ tools/build_landing_images.py)।
"""

FEATURES = [
    {
        'slug': 'online-shop', 'icon': 'bi-shop', 'image': 'shop', 'image_en': 'shop-en',
        'phone': 'shop-phone', 'phone_en': 'shop-phone-en',
        'related': ['facebook-page-website', 'courier-integration', 'landing-page', 'inventory'],
        'bn': {
            'nav': 'অনলাইন শপ ওয়েবসাইট',
            'title': '১ মিনিটে ই-কমার্স ওয়েবসাইট তৈরি করুন — কোড ছাড়া',
            'description': 'দোকানের নাম আর পছন্দের ঠিকানা দিন, ১ মিনিটে ই-কমার্স ওয়েবসাইট চালু। ক্যাশ অন ডেলিভারি, '
                           'bKash/Nagad পেমেন্ট, কুরিয়ার বুকিং। মাসে ৪৯৯ টাকা থেকে, ৩০ দিন ফ্রি।',
            'h1': '১ মিনিটে নিজের <em>ই-কমার্স ওয়েবসাইট</em> — কোড, ডেভেলপার বা হোস্টিং ছাড়া',
            'lead': 'দোকানের নাম আর পছন্দের ঠিকানা (যেমন yourshop.sellpunch.com) দিলেই ওয়েবসাইট চালু। তারপর প্রোডাক্টের ছবি '
                    'আর দাম তুলুন — কাস্টমার মোবাইল থেকে দেখে অর্ডার করবে, অর্ডার আসবে আপনার ড্যাশবোর্ডে।',
            'points': [
                ('bi-lightning-charge-fill', '১ মিনিটে চালু',
                 'সাইনআপে দোকানের নাম, ঠিকানা, মোবাইল নম্বর আর পাসওয়ার্ড — এই চারটা জিনিস। ডোমেইন কেনা, হোস্টিং, '
                 'ডিজাইনার — কিছুই লাগে না।'),
                ('bi-palette-fill', '৪টা ডিজাইন, নিজের রং',
                 'চারটা তৈরি ডিজাইন আর ছয়টা রং; চাইলে নিজের ব্র্যান্ডের রং। লোগো আর ব্যানার দিলেই ওয়েবসাইট আপনার মতো।'),
                ('bi-cash-coin', 'ক্যাশ অন ডেলিভারি আর অগ্রিম',
                 'কাস্টমার ক্যাশ অন ডেলিভারিতে অর্ডার দিতে পারে, অথবা bKash, Nagad বা কার্ডে আগে টাকা দিতে পারে — '
                 'পুরো টাকা নাকি শুধু ডেলিভারি চার্জ, নিয়ম আপনি ঠিক করবেন।'),
                ('bi-truck', 'এলাকাভিত্তিক ডেলিভারি চার্জ',
                 'ঢাকার ভেতরে আর বাইরে আলাদা চার্জ, নির্দিষ্ট টাকার উপরে ফ্রি ডেলিভারি। অর্ডার এলে এক ক্লিকে '
                 'Steadfast, Pathao বা RedX-এ পার্সেল বুক।'),
                ('bi-translate', 'বাংলা বা English',
                 'কাস্টমারের ওয়েবসাইট বাংলায় না ইংরেজিতে দেখাবে, এক ক্লিকে বদলান। ড্যাশবোর্ড পুরোটা বাংলায়।'),
                ('bi-search', 'Google-এ খুঁজে পাওয়ার ব্যবস্থা',
                 'প্রতিটা প্রোডাক্টের আলাদা পাতা, সাইটম্যাপ, Google-এর প্রোডাক্ট কার্ডের তথ্য — নিজে থেকে। '
                 'Facebook-এ লিংক দিলে ছবি আর দাম সুন্দর করে দেখায়।'),
                ('bi-ticket-perforated-fill', 'কুপন, রিভিউ, WhatsApp অর্ডার',
                 'টাকা বা শতাংশ ছাড়ের কুপন, কাস্টমারের রিভিউ (আপনি অনুমোদন দিলে দেখায়), আর WhatsApp-এ সরাসরি অর্ডারের বাটন।'),
                ('bi-globe2', 'নিজের ডোমেইন (Premium)',
                 'www.yourshop.com-এর মতো নিজের ডোমেইন — DNS-এ একটা রেকর্ড বসালেই চালু।'),
            ],
            'faq': [
                ('ই-কমার্স ওয়েবসাইট বানাতে কত টাকা লাগে?',
                 'SellPunch-এ মাসে ৪৯৯ টাকা থেকে, প্রথম ৩০ দিন ফ্রি। আলাদা ডোমেইন, হোস্টিং বা ডেভেলপারের খরচ নেই — '
                 'ওয়েবসাইটের সাথে POS, অর্ডার, কুরিয়ার আর হিসাবও পাচ্ছেন।'),
                ('সত্যিই কি ১ মিনিটে ওয়েবসাইট চালু হয়?',
                 'হ্যাঁ। সাইনআপ ফর্মে দোকানের নাম, পছন্দের ঠিকানা, মোবাইল নম্বর আর পাসওয়ার্ড দিলেই আপনার ঠিকানায় '
                 'ওয়েবসাইট খুলে যায়। এরপর প্রোডাক্ট তুললেই কাস্টমার অর্ডার করতে পারবে।'),
                ('কোড বা ওয়েবসাইট বানানো জানতে হবে?',
                 'না। Facebook চালাতে পারলেই পারবেন — প্রোডাক্টের ছবি, নাম, দাম আর স্টক লিখে সেভ করলেই ওয়েবসাইটে চলে আসে।'),
                ('মোবাইল দিয়ে চালানো যাবে?',
                 'হ্যাঁ, কোনো অ্যাপ ইনস্টল লাগে না। ফোনের ব্রাউজার থেকেই প্রোডাক্ট তোলা, অর্ডার দেখা, কুরিয়ারে পাঠানো — সব।'),
                ('পরে নিজের ডোমেইন (.com) লাগানো যাবে?',
                 'Premium প্যাকেজে নিজের ডোমেইন লাগানো যায়। তার আগ পর্যন্ত yourshop.sellpunch.com ঠিকানা ফ্রি।'),
            ],
        },
        'en': {
            'nav': 'Online store website',
            'title': 'Ecommerce Website Builder in Bangladesh — Live in 1 Minute',
            'description': 'Create your ecommerce website in 1 minute: pick a shop name and address, no code or hosting. '
                           'Cash on delivery, bKash/Nagad, courier booking. From BDT 499/month, 30 days free.',
            'h1': 'Your own <em>ecommerce website</em> in 1 minute — no code, developer or hosting',
            'lead': 'Enter your shop name and the address you want (like yourshop.sellpunch.com) and your website is live. '
                    'Add product photos and prices — customers order from their phones and orders land in your dashboard.',
            'points': [
                ('bi-lightning-charge-fill', 'Live in 1 minute',
                 'Sign-up asks for four things: shop name, web address, mobile number and password. No domain, hosting '
                 'or designer needed.'),
                ('bi-palette-fill', '4 designs, your colours',
                 'Four ready-made designs and six colours, or your own brand colour. Add a logo and banner and it looks like you.'),
                ('bi-cash-coin', 'Cash on delivery or advance payment',
                 'Customers can order cash on delivery or pay in advance with bKash, Nagad or card — the full amount or '
                 'just the delivery charge, your rule.'),
                ('bi-truck', 'Area-based delivery charges',
                 'Separate charges inside and outside Dhaka, free delivery above an amount. Book the parcel with Steadfast, '
                 'Pathao or RedX in one click.'),
                ('bi-translate', 'Bangla or English',
                 'Show your store in Bangla or English with one click. The seller dashboard is fully in Bangla.'),
                ('bi-search', 'Built for Google',
                 'A page for every product, a sitemap and Google product data, automatically. Links shared on Facebook '
                 'show the photo and price.'),
                ('bi-ticket-perforated-fill', 'Coupons, reviews, WhatsApp orders',
                 'Fixed or percentage coupons, customer reviews (shown when you approve), and a button to order straight on WhatsApp.'),
                ('bi-globe2', 'Your own domain (Premium)',
                 'Use www.yourshop.com — add one DNS record and it is live.'),
            ],
            'faq': [
                ('How much does an ecommerce website cost in Bangladesh?',
                 'With SellPunch it starts at BDT 499 a month, and the first 30 days are free. No separate domain, hosting '
                 'or developer costs — and you also get POS, orders, courier booking and accounts.'),
                ('Is the website really live in 1 minute?',
                 'Yes. Enter your shop name, web address, mobile number and password, and your website opens at that address. '
                 'Add products and customers can start ordering.'),
                ('Do I need to know coding?',
                 'No. If you can use Facebook you can use SellPunch — type the product photo, name, price and stock, save, '
                 'and it is on your website.'),
                ('Can I run it from my phone?',
                 'Yes, no app to install. Add products, see orders and send parcels from your phone browser.'),
                ('Can I use my own .com domain later?',
                 'Yes, on the Premium plan. Until then your yourshop.sellpunch.com address is free.'),
            ],
        },
    },
    {
        'slug': 'facebook-page-website', 'icon': 'bi-facebook', 'image': 'shop-phone', 'image_en': 'shop-phone-en',
        'tall': True,
        'related': ['facebook-auto-reply', 'online-shop', 'landing-page', 'courier-integration'],
        'bn': {
            'nav': 'ফেসবুক পেজের ওয়েবসাইট',
            'title': 'ফেসবুক পেজের জন্য ওয়েবসাইট — F-commerce সেলারদের অনলাইন শপ',
            'description': 'Facebook পেজের সব প্রোডাক্ট এক লিংকে। কাস্টমার নিজে অর্ডার করবে, ইনবক্সে দাম বলতে হবে না। '
                           '১ মিনিটে ওয়েবসাইট, কুরিয়ার বুকিং, অর্ডারের SMS। ৩০ দিন ফ্রি।',
            'h1': 'ফেসবুক পেজের জন্য <em>নিজের ওয়েবসাইট</em> — ইনবক্সে দাম বলার দিন শেষ',
            'lead': '"দাম কত?" "সাইজ আছে?" — প্রতিটা কমেন্টে একই উত্তর দিতে দিতে দিন চলে যায়। পেজের সব প্রোডাক্ট এক লিংকে দিন: '
                    'কাস্টমার ছবি, দাম, সাইজ দেখে নিজেই অর্ডার করবে, আর আপনি শুধু কনফার্ম করে কুরিয়ারে পাঠাবেন।',
            'points': [
                ('bi-link-45deg', 'পেজে এক লিংক, সব প্রোডাক্ট',
                 'ওয়েবসাইটের লিংক পেজের বায়ো, পোস্ট আর কমেন্টে দিন। প্রতিটা প্রোডাক্টের আলাদা লিংকও আছে — '
                 'পোস্টে শেয়ার করলে ছবি আর দাম দেখায়।'),
                ('bi-bag-check-fill', 'কাস্টমার নিজেই অর্ডার করে',
                 'নাম, মোবাইল, ঠিকানা লিখে অর্ডার — রাত তিনটায়ও। অর্ডার এলেই ড্যাশবোর্ডে দেখবেন, কাস্টমার SMS পাবে।'),
                ('bi-chat-dots-fill', 'কমেন্ট আর Messenger-এ অটো উত্তর',
                 'পেজ যুক্ত করলে (Standard ও Premium) কমেন্টকারীর ইনবক্সে দাম আর অর্ডারের লিংক, Messenger-এ দাম-ডেলিভারির '
                 'উত্তর আর চ্যাটেই অর্ডার — নিজে থেকে।'),
                ('bi-whatsapp', 'WhatsApp-এ অর্ডারের বাটন',
                 'যে কাস্টমার কথা বলে কিনতে চায়, তার জন্য ওয়েবসাইটেই WhatsApp-এ অর্ডারের বাটন।'),
                ('bi-shield-exclamation', 'ভুয়া অর্ডার চেনা',
                 'যে নম্বর আগে পার্সেল ফেরত দিয়েছে, তার অর্ডারের পাশেই সতর্কতা — পাঠানোর আগে ফোন করে নিন।'),
                ('bi-cart-x-fill', 'অসম্পূর্ণ অর্ডার',
                 'কার্টে রেখে চলে যাওয়া কাস্টমারের নম্বর দেখা যায় — একটা ফোনেই অনেক অর্ডার ফেরত আসে।'),
            ],
            'faq': [
                ('Facebook পেজ থাকলে আলাদা ওয়েবসাইট কেন লাগবে?',
                 'পেজে প্রোডাক্ট খুঁজতে কাস্টমারকে অনেক পোস্ট ঘাঁটতে হয়, আর প্রতিটা দাম ইনবক্সে বলতে হয়। ওয়েবসাইটে সব '
                 'প্রোডাক্ট সাজানো থাকে, কাস্টমার নিজে অর্ডার করে — আপনার সময় বাঁচে, অর্ডারও হারায় না।'),
                ('পেজের প্রোডাক্ট ওয়েবসাইটে তুলতে কত সময় লাগে?',
                 'একটা প্রোডাক্ট তুলতে এক মিনিটের মতো — ছবি, নাম, দাম, স্টক। সাইজ-রং থাকলে প্রতিটার আলাদা স্টক দিতে পারেন।'),
                ('ক্যাশ অন ডেলিভারি রাখা যাবে?',
                 'হ্যাঁ। চাইলে শুধু ক্যাশ অন ডেলিভারি, অথবা bKash/Nagad-এ অগ্রিম — পুরো টাকা বা শুধু ডেলিভারি চার্জ।'),
                ('ফ্রি ট্রায়ালে কী কী পাব?',
                 '৩০ দিন সব ফিচার ফ্রি — ওয়েবসাইট, অর্ডার, কুরিয়ার, POS। কার্ড লাগে না; পছন্দ না হলে কিছু করতে হবে না।'),
            ],
        },
        'en': {
            'nav': 'Website for Facebook page',
            'title': 'Website for Your Facebook Page — Online Store for F-commerce Sellers',
            'description': 'Put every product from your Facebook page behind one link. Customers order themselves — no more '
                           'price replies in the inbox. Website in 1 minute, courier booking, order SMS. 30 days free.',
            'h1': 'A <em>website for your Facebook page</em> — stop answering prices in the inbox',
            'lead': '"Price?" "Is my size available?" — answering the same comments all day takes your time. Put every product '
                    'behind one link: customers see photos, prices and sizes and order themselves, and you just confirm and ship.',
            'points': [
                ('bi-link-45deg', 'One link, every product',
                 'Put the website link in your page bio, posts and comments. Every product has its own link too, with photo '
                 'and price when shared.'),
                ('bi-bag-check-fill', 'Customers order on their own',
                 'Name, mobile and address — even at 3 a.m. Orders show up in your dashboard and the customer gets an SMS.'),
                ('bi-chat-dots-fill', 'Comment and Messenger auto reply',
                 'Connect your page (Standard and Premium): commenters get the price and order link in their inbox, Messenger '
                 'questions about price and delivery are answered, and orders are taken in the chat — automatically.'),
                ('bi-whatsapp', 'WhatsApp order button',
                 'For customers who want to talk first, a WhatsApp order button right on your website.'),
                ('bi-shield-exclamation', 'Spot fake orders',
                 'Numbers that returned parcels before get a warning next to their order — call before you ship.'),
                ('bi-cart-x-fill', 'Abandoned carts',
                 'See the numbers of customers who left items in the cart — one call brings many orders back.'),
            ],
            'faq': [
                ('Why do I need a website if I have a Facebook page?',
                 'On a page, customers scroll through posts to find products and ask every price in the inbox. A website keeps '
                 'everything organised and customers order themselves — you save time and lose fewer orders.'),
                ('How long does it take to add my page products?',
                 'About a minute per product — photo, name, price, stock. Sizes and colours can each have their own stock.'),
                ('Can I keep cash on delivery?',
                 'Yes. Cash on delivery only, or advance payment with bKash/Nagad — the full amount or just the delivery charge.'),
                ('What do I get in the free trial?',
                 'Every feature free for 30 days — website, orders, courier, POS. No card needed; if you do not like it, do nothing.'),
            ],
        },
    },
    {
        'slug': 'facebook-auto-reply', 'icon': 'bi-messenger', 'image': 'fb-auto', 'image_en': 'fb-auto',
        'phone': 'fb-inbox-phone', 'phone_en': 'fb-inbox-phone', 'facebook': True,
        'related': ['facebook-page-website', 'online-shop', 'courier-integration', 'landing-page'],
        'bn': {
            'nav': 'ফেসবুক অটো রিপ্লাই',
            'title': 'ফেসবুক পেজে অটো রিপ্লাই — কমেন্ট আর Messenger বট, বাংলায়',
            'description': 'কমেন্ট করলেই ইনবক্সে দাম আর অর্ডারের লিংক, Messenger-এ দিনরাত বাংলায় উত্তর, চ্যাটেই অর্ডার। '
                           'ফোন নম্বরের কমেন্ট নিজে লুকায়। ৩০ দিন ফ্রি।',
            'h1': 'ফেসবুক পেজের <em>অটো রিপ্লাই</em> — কমেন্টে, Messenger-এ, আর চ্যাটেই অর্ডার',
            'lead': '"দাম কত?" "ডেলিভারি চার্জ কত?" "আমার অর্ডার কোথায়?" — দিনে শত শত একই প্রশ্ন। পেজ যুক্ত করলে SellPunch '
                    'আপনার দোকানের আসল তথ্য দেখে নিজে থেকে উত্তর দেয়, আর যেটা আপনাকে দেখতে হবে শুধু সেটাই আপনার কাছে আসে।',
            'pending': 'Facebook-এর নিয়মে Meta প্রতিটা অ্যাপ আলাদা করে যাচাই করে। SellPunch-এর যাচাই এখন চলছে — শেষ হলেই সব '
                       'দোকানে এই সুবিধা চালু হবে। এর মধ্যে অ্যাকাউন্ট খুলে ওয়েবসাইট আর বাকি সব ফিচার ব্যবহার করতে পারবেন।',
            'points': [
                ('bi-chat-left-text-fill', 'কমেন্টে ইনবক্সে দাম আর লিংক',
                 'পোস্টে প্রোডাক্টের কোড (#P12) থাকলে কমেন্টকারীর ইনবক্সে সেই প্রোডাক্টের নাম, দাম আর অর্ডারের লিংক যায়; '
                 'কমেন্টের নিচে ছোট উত্তর। একজনকে এক পোস্টে একবারই — স্প্যাম হয় না।'),
                ('bi-eye-slash-fill', 'ফোন নম্বরের কমেন্ট লুকানো',
                 'কাস্টমারের নম্বর লেখা কমেন্ট, অন্য পেজের লিংক আর আপনার বাছাই করা শব্দের কমেন্ট নিজে থেকে লুকায় — '
                 'অন্য দোকান আপনার কাস্টমারের নম্বর নিতে পারে না।'),
                ('bi-messenger', 'Messenger-এ দিনরাত উত্তর',
                 'দাম, ডেলিভারি চার্জ, পেমেন্টের নিয়ম, ঠিকানা, রিটার্ন পলিসি — দোকানের তথ্য থেকে সাথে সাথে উত্তর। '
                 'বাংলা, ইংরেজি আর বাংলিশ ("dam koto") বোঝে।'),
                ('bi-bag-check-fill', 'চ্যাটেই অর্ডার',
                 'সাইজ, কয়টা, নাম, মোবাইল, ঠিকানা আর এলাকা জেনে বট নিজেই অর্ডার বানায় — ক্যাশ অন ডেলিভারিতে, '
                 'স্টক মিলিয়ে, ব্লক করা নম্বর আটকে। অর্ডার আসে আপনার অর্ডারের তালিকায়।'),
                ('bi-truck', 'অর্ডারের খবর Messenger-এ',
                 'কনফার্ম, কুরিয়ারে দেওয়া (ট্র্যাকিং কোডসহ), ডেলিভারি — কাস্টমার Messenger-এ জানে, SMS-এর খরচ ছাড়াই। '
                 '"অর্ডার কোথায়?" জিজ্ঞেস করলে বট নিজেই বলে দেয়।'),
                ('bi-question-circle-fill', 'নিজের প্রশ্ন-উত্তর',
                 'সাইজ চার্ট, কাপড়, এক্সচেঞ্জ — যে প্রশ্ন বারবার আসে তার উত্তর একবার লিখে রাখুন। কোন উত্তর কতবার গেল, তা-ও দেখবেন।'),
                ('bi-person-raised-hand', 'দরকার হলে মানুষ',
                 'কাস্টমার মানুষের সাথে কথা বলতে চাইলে বা ছবি পাঠালে বট সরে যায়, কথোপকথন আসে আপনার "অপেক্ষায়" তালিকায়। '
                 'আপনি নিজে উত্তর দিলে বট সেই কাস্টমারের সাথে ১২ ঘণ্টা চুপ থাকে।'),
                ('bi-graph-up-arrow', 'Facebook থেকে কত বিক্রি',
                 'কমেন্ট, Messenger-এর লিংক আর চ্যাট থেকে কয়টা অর্ডার আর কত টাকা — কোন পোস্ট সবচেয়ে বেশি বিক্রি আনল, '
                 'যাতে বুস্টের টাকা ঠিক পোস্টে যায়।'),
            ],
            'steps': [
                ('অ্যাকাউন্ট খুলুন', '১ মিনিটে দোকান আর ওয়েবসাইট চালু; প্রোডাক্টের ছবি আর দাম তুলুন।'),
                ('Facebook পেজ যুক্ত করুন', 'সেটিংস → Facebook → পেজ বাছুন। কমেন্ট আর Messenger-এর অটো রিপ্লাই সাথে সাথে চালু।'),
                ('পোস্টে কোড দিন', 'পোস্টে প্রোডাক্টের কোড (#P12) লিখুন — কমেন্টকারী ইনবক্সে সেই প্রোডাক্টের দাম আর অর্ডারের লিংক পাবে।'),
            ],
            'faq': [
                ('ফেসবুক পেজে অটো রিপ্লাই কীভাবে চালু করব?',
                 'SellPunch-এ অ্যাকাউন্ট খুলে সেটিংস → Facebook থেকে পেজ যুক্ত করুন — কমেন্ট আর Messenger-এর অটো রিপ্লাই সাথে '
                 'সাথে চালু হয়। তারপর স্বাগত মেসেজ, নিজের প্রশ্ন-উত্তর আর কোন কমেন্ট লুকাবে ঠিক করে নিন। ধাপে ধাপে দেখতে '
                 'গাইড সেন্টারের "Facebook অটো রিপ্লাই" গাইড দেখুন।'),
                ('Meta Business Suite-এর অটো রিপ্লাইয়ের সাথে পার্থক্য কী?',
                 'Meta-র অটো রিপ্লাই আগে থেকে লেখা একই উত্তর পাঠায়। SellPunch-এর বট আপনার দোকানের আসল তথ্য দেখে উত্তর দেয় — '
                 'কোন প্রোডাক্টের দাম কত, স্টকে আছে কিনা, কোন এলাকায় ডেলিভারি চার্জ কত, অর্ডার কোথায় — আর চ্যাটেই অর্ডার নিয়ে '
                 'আপনার অর্ডারের তালিকায় তোলে। দুটো একসাথে চালু রাখবেন না।'),
                ('কোন প্যাকেজে পাব, খরচ কত?',
                 'Standard (মাসে ৯৯৯ টাকা) আর Premium (মাসে ১,৯৯৯ টাকা) প্যাকেজে, আর ৩০ দিনের ফ্রি ট্রায়ালেও। কমেন্ট বা '
                 'Messenger-এর উত্তরের জন্য আলাদা কোনো খরচ নেই।'),
                ('বট না বুঝলে বা কাস্টমার মানুষের সাথে কথা বলতে চাইলে?',
                 'বট জানিয়ে দেয় যে দোকানের একজন শীঘ্রই উত্তর দেবেন, আর কথোপকথনটা আপনার "উত্তরের অপেক্ষায়" তালিকায় আসে। '
                 'আপনি Page Inbox থেকে উত্তর দিলে বট ১২ ঘণ্টা চুপ থাকে; কোনো কাস্টমারের সাথে বট থামিয়েও রাখা যায়।'),
                ('বট কি ইংরেজিতেও উত্তর দেয়?',
                 'হ্যাঁ। দোকানের ওয়েবসাইট English-এ থাকলে বটের উত্তর, বাটন আর অর্ডারের খবর ইংরেজিতে যায়। কাস্টমার বাংলা, '
                 'ইংরেজি বা বাংলিশে লিখলেও বোঝে।'),
                ('Facebook-এর ২৪ ঘণ্টার নিয়ম মানা হয়?',
                 'হ্যাঁ। কাস্টমারের শেষ মেসেজের ২৪ ঘণ্টা পর Facebook সাধারণ মেসেজ পাঠাতে দেয় না — তখন শুধু তার অর্ডারের খবর '
                 '(কনফার্ম, কুরিয়ার, ডেলিভারি) যায়, Facebook-এর অনুমোদিত নিয়মে।'),
            ],
        },
        'en': {
            'nav': 'Facebook auto reply',
            'title': 'Facebook Page Auto Reply — Comment & Messenger Bot, Bangladesh',
            'description': 'Facebook page auto reply: price and order link in the inbox for every comment, a Messenger bot that '
                           'answers day and night, orders in the chat. 30 days free.',
            'h1': '<em>Auto reply</em> for your Facebook page — comments, Messenger, and orders in the chat',
            'lead': '"Price?" "Delivery charge?" "Where is my order?" — the same questions hundreds of times a day. Connect your page '
                    'and SellPunch answers from your real shop data, and only what needs you comes to you.',
            'pending': 'Meta reviews every app that works with Facebook pages. SellPunch is in that review now — once it is '
                       'approved, this turns on for every shop. Meanwhile you can open an account and use the website and every '
                       'other feature.',
            'points': [
                ('bi-chat-left-text-fill', 'Price and link in the inbox',
                 'When a post has a product code (#P12), commenters get that product\'s name, price and order link in their '
                 'inbox, plus a short reply under the comment. Once per person per post, so it never spams.'),
                ('bi-eye-slash-fill', 'Hide comments with phone numbers',
                 'Comments with a customer\'s number, links to other pages or words you choose are hidden automatically, so '
                 'other sellers cannot take your customers\' numbers.'),
                ('bi-messenger', 'Messenger answers, day and night',
                 'Prices, delivery charges, payment rules, address and return policy, answered from your shop data instantly. '
                 'Understands Bangla, English and Banglish ("dam koto").'),
                ('bi-bag-check-fill', 'Orders right in the chat',
                 'The bot asks size, quantity, name, mobile, address and area and creates the order — cash on delivery, '
                 'stock-checked, blocked numbers refused. It lands in your order list.'),
                ('bi-truck', 'Order updates on Messenger',
                 'Confirmed, handed to the courier (with tracking code), delivered — customers hear it on Messenger, no SMS cost. '
                 'Ask "where is my order?" and the bot answers.'),
                ('bi-question-circle-fill', 'Your own Q&A',
                 'Size charts, fabric, exchanges — write the answer once for questions you get every day, and see how often each '
                 'one was sent.'),
                ('bi-person-raised-hand', 'A person when needed',
                 'If a customer asks for a person or sends a photo, the bot steps aside and the chat joins your waiting list. '
                 'When you reply yourself, the bot stays quiet with that customer for 12 hours.'),
                ('bi-graph-up-arrow', 'Sales from Facebook',
                 'Orders and revenue from comments, Messenger links and chat orders — and which post sold the most, so your boost '
                 'money goes to the right post.'),
            ],
            'steps': [
                ('Open an account', 'Your shop and website are live in 1 minute; add product photos and prices.'),
                ('Connect your Facebook page', 'Settings → Facebook → choose your page. Comment and Messenger auto reply start right away.'),
                ('Add codes to posts', 'Write the product code (#P12) in a post — commenters get that product\'s price and order link in their inbox.'),
            ],
            'faq': [
                ('How do I turn on auto reply for my Facebook page?',
                 'Open a SellPunch account and connect your page from Settings → Facebook — comment and Messenger auto reply start '
                 'right away. Then set your welcome message, your own Q&A and which comments to hide. The guide centre has a '
                 'step-by-step guide (in Bangla).'),
                ('How is it different from Meta Business Suite auto replies?',
                 'Meta\'s automated replies send the same pre-written text. SellPunch answers from your real shop data — the price '
                 'of a product, whether it is in stock, the delivery charge for an area, where an order is — and takes orders in '
                 'the chat straight into your order list. Do not run both at once.'),
                ('Which plans include it, and what does it cost?',
                 'Standard (BDT 999 a month) and Premium (BDT 1,999 a month), and the 30-day free trial. There is no extra charge '
                 'for comment or Messenger replies.'),
                ('What if the bot does not understand, or the customer wants a person?',
                 'The bot says someone from the shop will reply soon and the chat joins your "waiting" list. When you reply from '
                 'the Page Inbox, the bot stays quiet for 12 hours; you can also pause it for any customer.'),
                ('Does the bot reply in English?',
                 'Yes. If your store is set to English, the bot\'s replies, buttons and order updates are in English. It also '
                 'understands customers writing in Bangla, English or Banglish.'),
                ('Does it follow Facebook\'s 24-hour rule?',
                 'Yes. After 24 hours from a customer\'s last message Facebook does not allow ordinary messages, so only that '
                 'customer\'s order updates (confirmed, courier, delivered) are sent, using Facebook\'s approved method.'),
            ],
        },
    },
    {
        'slug': 'pos-software', 'icon': 'bi-upc-scan', 'image': 'pos', 'image_en': 'pos',
        'phone': 'pos-phone', 'phone_en': 'pos-phone',
        'related': ['inventory', 'due-book', 'accounting', 'online-shop'],
        'bn': {
            'nav': 'POS সফটওয়্যার',
            'title': 'POS সফটওয়্যার — দোকানের বিলিং, বারকোড, রসিদ (বাংলায়)',
            'description': 'দোকানের জন্য বাংলা POS সফটওয়্যার: বারকোড স্ক্যান, রসিদ প্রিন্ট, নগদ-bKash-কার্ড, বাকি, স্টক আর '
                           'লাভের হিসাব। অনলাইন শপের সাথে একই স্টক। মাসে ৪৯৯ টাকা থেকে, ৩০ দিন ফ্রি।',
            'h1': 'দোকানের জন্য <em>POS সফটওয়্যার</em> — বারকোড, রসিদ আর পুরো হিসাব বাংলায়',
            'lead': 'কাউন্টারে বারকোড স্ক্যান করুন বা নাম লিখে খুঁজুন, টাকা নিন, রসিদ দিন। দোকানের বিক্রি আর অনলাইনের অর্ডার '
                    'একই স্টক থেকে কমে — রাতে খাতা মেলানোর ঝামেলা নেই।',
            'points': [
                ('bi-upc-scan', 'বারকোড স্ক্যান আর নাম দিয়ে খোঁজা',
                 'স্ক্যানার দিয়ে বা নাম লিখে প্রোডাক্ট খুঁজুন; সাইজ-রং থাকলে প্রতিটার আলাদা স্টক আর দাম।'),
                ('bi-wallet2', 'নগদ, bKash, কার্ড — একসাথে',
                 'এক বিলে কিছু নগদ, কিছু bKash — মিলিয়ে নেওয়া যায়। ছাড়, VAT আর ফেরত টাকার হিসাব নিজে থেকে।'),
                ('bi-printer-fill', 'রসিদ আর বারকোড স্টিকার প্রিন্ট',
                 'POS প্রিন্টার বা A4-এ রসিদ, লোগো আর ফেরতের নিয়মসহ। প্রোডাক্টে লাগানোর বারকোড স্টিকারও ছাপা যায়।'),
                ('bi-journal-text', 'বাকিতে বিক্রি',
                 'চেনা কাস্টমারকে বাকিতে দিন — কার কাছে কত বাকি, কবে দেবে বলেছে, সব বাকির খাতায় চলে যায়।'),
                ('bi-people-fill', 'স্টাফ অ্যাকাউন্ট',
                 'ক্যাশিয়ার শুধু POS দেখবে, রিপোর্ট বা লাভ না — কে কী দেখবে আপনি ঠিক করবেন।'),
                ('bi-phone', 'মোবাইল বা কম্পিউটার — দুটোতেই',
                 'আলাদা মেশিন কেনার দরকার নেই। দোকানের কম্পিউটার, ট্যাব বা ফোনের ব্রাউজারেই চলে।'),
            ],
            'faq': [
                ('POS সফটওয়্যারের দাম কত?',
                 'SellPunch-এর POS মাসে ৪৯৯ টাকা থেকে, প্রথম ৩০ দিন ফ্রি। একই দামে অনলাইন শপ ওয়েবসাইট, অর্ডার আর কুরিয়ারও পাচ্ছেন।'),
                ('কোন বারকোড স্ক্যানার আর প্রিন্টার লাগবে?',
                 'সাধারণ USB বারকোড স্ক্যানার (যেটা কিবোর্ডের মতো লেখে) আর যেকোনো থার্মাল POS প্রিন্টার বা A4 প্রিন্টার চলে।'),
                ('ইন্টারনেট লাগবে?',
                 'হ্যাঁ, SellPunch অনলাইনে চলে — তাই দোকান, বাসা বা ফোন, যেখান থেকেই দেখুন একই হিসাব।'),
                ('একাধিক স্টাফ চালাতে পারবে?',
                 'হ্যাঁ। Standard-এ ৩ জন, Premium-এ ১০ জন স্টাফ; প্রত্যেকের আলাদা লগইন আর অনুমতি।'),
            ],
        },
        'en': {
            'nav': 'POS software',
            'title': 'POS Software in Bangladesh — Billing, Barcode & Receipts',
            'description': 'Bangla POS software for shops in Bangladesh: barcode scanning, receipt printing, cash/bKash/card, '
                           'dues, stock and profit. Same stock as your online store. From BDT 499/month, 30 days free.',
            'h1': '<em>POS software</em> for shops in Bangladesh — barcode, receipts and full accounts',
            'lead': 'Scan a barcode or search by name, take payment and print a receipt. Counter sales and online orders come out '
                    'of the same stock — no matching notebooks at night.',
            'points': [
                ('bi-upc-scan', 'Barcode scan and name search',
                 'Find products with a scanner or by name; sizes and colours have their own stock and price.'),
                ('bi-wallet2', 'Cash, bKash, card — together',
                 'Split one bill between cash and bKash. Discounts, VAT and change are calculated for you.'),
                ('bi-printer-fill', 'Receipts and barcode stickers',
                 'Print receipts on a POS printer or A4 with your logo and return policy. Print barcode stickers for products too.'),
                ('bi-journal-text', 'Sell on credit',
                 'Give regular customers credit — who owes how much and the promised date go straight to the due book.'),
                ('bi-people-fill', 'Staff accounts',
                 'Cashiers see only the POS, not reports or profit — you decide who sees what.'),
                ('bi-phone', 'Phone or computer',
                 'No special machine to buy. Runs in the browser on your shop computer, tablet or phone.'),
            ],
            'faq': [
                ('What is the price of POS software in Bangladesh?',
                 'SellPunch POS starts at BDT 499 a month, first 30 days free — and the same price includes an online store, '
                 'orders and courier booking.'),
                ('Which barcode scanner and printer work?',
                 'Any ordinary USB barcode scanner (one that types like a keyboard) and any thermal POS printer or A4 printer.'),
                ('Does it need internet?',
                 'Yes, SellPunch runs online — so the shop, home and your phone all show the same accounts.'),
                ('Can several staff use it?',
                 'Yes. 3 staff on Standard and 10 on Premium, each with their own login and permissions.'),
            ],
        },
    },
    {
        'slug': 'courier-integration', 'icon': 'bi-truck', 'image': 'orders', 'image_en': 'orders',
        'phone': 'track-phone', 'phone_en': 'track-phone-en',
        'related': ['online-shop', 'facebook-page-website', 'accounting', 'landing-page'],
        'bn': {
            'nav': 'কুরিয়ার বুকিং',
            'title': 'Steadfast, Pathao, RedX কুরিয়ার বুকিং — এক ক্লিকে',
            'description': 'অর্ডার থেকে এক ক্লিকে Steadfast, Pathao বা RedX-এ পার্সেল বুক, ট্র্যাকিং কোড নিজে বসে, কাস্টমার SMS পায়। '
                           'তিনটা কুরিয়ারই আসল অ্যাকাউন্টে পরীক্ষিত। ৩০ দিন ফ্রি।',
            'h1': '<em>Steadfast, Pathao, RedX</em> — অর্ডার থেকে এক ক্লিকে কুরিয়ারে',
            'lead': 'প্রতিটা অর্ডারের নাম-ঠিকানা কুরিয়ারের সাইটে আবার লিখতে হবে না। অর্ডার কনফার্ম করে কুরিয়ার বেছে নিন — '
                    'পার্সেল বুক হয়, ট্র্যাকিং কোড অর্ডারে বসে, কাস্টমার SMS আর ট্র্যাকিং লিংক পায়।',
            'points': [
                ('bi-box-seam-fill', 'এক ক্লিকে পার্সেল বুক',
                 'নিজের মার্চেন্ট অ্যাকাউন্টের চাবি একবার বসান; তারপর প্রতিটা অর্ডার এক ক্লিকে — নাম, ঠিকানা, COD-এর টাকা নিজে থেকে যায়।'),
                ('bi-patch-check-fill', 'তিনটাই আসল অ্যাকাউন্টে পরীক্ষিত',
                 'Steadfast, Pathao আর RedX — তিনটা কুরিয়ারেই আসল পার্সেল বুক করে পরীক্ষা করা।'),
                ('bi-geo-alt-fill', 'ট্র্যাকিং লিংক',
                 'কাস্টমার নিজের ফোনে দেখে অর্ডার কোথায় — "ভাই পার্সেল কই" ফোন কমে।'),
                ('bi-chat-left-text-fill', 'অটো SMS',
                 'অর্ডার পেলে, কনফার্ম হলে, কুরিয়ারে গেলে — কোন SMS যাবে আপনি ঠিক করবেন, চাইলে বন্ধও রাখতে পারেন।'),
                ('bi-arrow-counterclockwise', 'রিটার্ন আর বাতিল',
                 'পার্সেল ফেরত এলে স্টক আবার যোগ হয়, হিসাব থেকে বাদ যায় — নিজে থেকে।'),
                ('bi-shield-exclamation', 'আগে ফেরত দেওয়া নম্বরে সতর্কতা',
                 'যে নম্বর আগে পার্সেল ফেরত দিয়েছে, পাঠানোর আগেই অর্ডারের পাশে দেখবেন।'),
            ],
            'faq': [
                ('কোন কোন কুরিয়ারের সাথে কাজ করে?',
                 'Steadfast, Pathao আর RedX। তিনটাই আসল মার্চেন্ট অ্যাকাউন্টে পার্সেল বুক করে পরীক্ষা করা।'),
                ('কুরিয়ারের চার্জ কি SellPunch নেয়?',
                 'না। পার্সেল বুক হয় আপনার নিজের মার্চেন্ট অ্যাকাউন্টে — চার্জ আর COD-এর টাকা কুরিয়ার আপনার সাথেই হিসাব করে।'),
                ('কুরিয়ারে পাঠানোর পর কাস্টমার কী পায়?',
                 'অটো SMS চালু থাকলে ট্র্যাকিং লিংকসহ SMS যায় — কাস্টমার নিজেই দেখে পার্সেল কোথায়।'),
                ('কুরিয়ার অ্যাকাউন্ট না থাকলে?',
                 'সংশ্লিষ্ট কুরিয়ারের সাইটে ফ্রি মার্চেন্ট অ্যাকাউন্ট খুলে API চাবি নিন, তারপর SellPunch-এর কুরিয়ার সেটিংসে বসান।'),
            ],
        },
        'en': {
            'nav': 'Courier booking',
            'title': 'Steadfast, Pathao & RedX Courier Booking — One Click',
            'description': 'Book parcels with Steadfast, Pathao or RedX straight from the order, tracking code saved, customer gets '
                           'an SMS. All three tested on live merchant accounts. 30 days free.',
            'h1': '<em>Steadfast, Pathao, RedX</em> — from order to courier in one click',
            'lead': 'Stop retyping every name and address on the courier website. Confirm the order and pick a courier — the parcel '
                    'is booked, the tracking code is saved and the customer gets an SMS and a tracking link.',
            'points': [
                ('bi-box-seam-fill', 'One-click booking',
                 'Add your merchant API keys once; then book each order in one click — name, address and COD amount go automatically.'),
                ('bi-patch-check-fill', 'Tested on live accounts',
                 'Steadfast, Pathao and RedX — all three tested by booking real parcels.'),
                ('bi-geo-alt-fill', 'Tracking link',
                 'Customers check where their order is on their phone — fewer "where is my parcel" calls.'),
                ('bi-chat-left-text-fill', 'Automatic SMS',
                 'When the order is received, confirmed and shipped — you choose which SMS go out, or switch them off.'),
                ('bi-arrow-counterclockwise', 'Returns and cancellations',
                 'Returned parcels go back into stock and out of your sales — automatically.'),
                ('bi-shield-exclamation', 'Warning for past returners',
                 'Numbers that returned parcels before are flagged next to the order before you ship.'),
            ],
            'faq': [
                ('Which couriers does it work with?',
                 'Steadfast, Pathao and RedX — all three tested by booking parcels on live merchant accounts.'),
                ('Does SellPunch take a courier fee?',
                 'No. Parcels are booked on your own merchant account; charges and COD money are settled between you and the courier.'),
                ('What does the customer get after shipping?',
                 'With automatic SMS on, an SMS with a tracking link — customers check the parcel themselves.'),
                ('What if I have no courier account?',
                 'Open a free merchant account on the courier website, get the API keys, and add them in SellPunch courier settings.'),
            ],
        },
    },
    {
        'slug': 'due-book', 'icon': 'bi-journal-text', 'image': 'dues', 'image_en': 'dues',
        'related': ['pos-software', 'accounting', 'inventory', 'online-shop'],
        'bn': {
            'nav': 'বাকির খাতা',
            'title': 'বাকির খাতা — ডিজিটাল হিসাব আর তাগাদার SMS',
            'description': 'কাগজের বাকির খাতার বদলে ডিজিটাল খাতা: কার কাছে কত বাকি, কবে দেবে, পুরনো বাকি — এক নজরে। '
                           'একজনকে বা সবাইকে তাগাদার SMS, নিজে থেকে মনে করানো। ৩০ দিন ফ্রি।',
            'h1': '<em>বাকির খাতা</em> — কার কাছে কত বাকি, কবে দেবে, আর ভুলে যাওয়া না',
            'lead': 'কাগজের খাতা হারায়, পাতা ছেঁড়ে, হিসাব মেলে না। POS-এ বাকিতে বিক্রি করলেই খাতায় ওঠে — কে কত দিন ধরে বাকি '
                    'রেখেছে, কথা দেওয়া তারিখ পার হলো কিনা, সব এক তালিকায়।',
            'points': [
                ('bi-list-check', 'সব বাকি এক তালিকায়',
                 'কাস্টমার ধরে মোট বাকি, কত দিনের পুরনো, শেষ কবে টাকা দিয়েছে — সাজানো।'),
                ('bi-calendar-event-fill', 'কথা দেওয়া তারিখ',
                 '"সামনের মাসের ৫ তারিখে দেব" — তারিখ লিখে রাখুন; পার হলে তালিকায় আলাদা করে দেখাবে।'),
                ('bi-chat-left-text-fill', 'তাগাদার SMS',
                 'একজনকে বা সবাইকে এক ক্লিকে SMS, নাম আর টাকার অঙ্কসহ।'),
                ('bi-arrow-repeat', 'নিজে থেকে মনে করানো',
                 '৭, ১৫ বা ৩০ দিন পর পর নিজে থেকে তাগাদা — আপনি চালু রাখলে।'),
                ('bi-cash-stack', 'আংশিক জমা',
                 'কিছু টাকা দিলে সেটাই লিখুন — নগদ বা bKash, বাকিটা নিজে থেকে হিসাব হয়।'),
                ('bi-file-earmark-excel-fill', 'Excel-এ নামানো',
                 'কাস্টমার আর টাকা আদায়ের পুরো হিসাব যেকোনো সময় Excel-এ নিয়ে রাখতে পারেন।'),
            ],
            'faq': [
                ('বাকির খাতা অ্যাপ কি আলাদা কিনতে হবে?',
                 'না। SellPunch-এর POS আর অর্ডারের সাথেই বাকির খাতা আছে — বাকিতে বিক্রি করলেই খাতায় ওঠে।'),
                ('তাগাদার SMS-এর খরচ কত?',
                 'SMS-এর ব্যালেন্স আলাদা কিনতে হয়, অনলাইনে পেমেন্ট করে। কতগুলো যাবে, কাকে যাবে — সব আপনার হাতে।'),
                ('পুরনো খাতার বাকি তোলা যাবে?',
                 'হ্যাঁ, কাস্টমার যোগ করে আগের বাকি লিখে দিলেই হিসাব শুরু।'),
                ('কাস্টমার কি নিজের বাকি দেখতে পারে?',
                 'তাগাদার SMS-এ নাম আর বাকির অঙ্ক যায়, তাই কাস্টমার জানে কত দিতে হবে।'),
            ],
        },
        'en': {
            'nav': 'Due book (baki khata)',
            'title': 'Digital Due Book (Baki Khata) with Reminder SMS',
            'description': 'Replace the paper baki khata: who owes how much, since when, the promised date — at a glance. '
                           'Reminder SMS to one or all, automatic reminders. 30 days free.',
            'h1': 'A digital <em>due book</em> — who owes what, when they will pay, and no forgetting',
            'lead': 'Paper notebooks get lost and never add up. Sell on credit at the POS and it goes straight into the due book — '
                    'how long each due has been open and whether the promised date has passed, in one list.',
            'points': [
                ('bi-list-check', 'Every due in one list',
                 'Total due per customer, how old it is and the last payment — sorted.'),
                ('bi-calendar-event-fill', 'Promised dates',
                 'Note "I will pay on the 5th" and overdue promises stand out in the list.'),
                ('bi-chat-left-text-fill', 'Reminder SMS',
                 'One click to remind one customer or everyone, with their name and amount.'),
                ('bi-arrow-repeat', 'Automatic reminders',
                 'Reminders every 7, 15 or 30 days — if you switch them on.'),
                ('bi-cash-stack', 'Part payments',
                 'Record whatever they pay — cash or bKash — and the rest is calculated.'),
                ('bi-file-earmark-excel-fill', 'Excel export',
                 'Download customers and every payment to Excel at any time.'),
            ],
            'faq': [
                ('Do I need a separate due book app?',
                 'No. The due book comes with SellPunch POS and orders — credit sales go into it automatically.'),
                ('How much do reminder SMS cost?',
                 'SMS balance is bought separately with online payment. You decide how many go out and to whom.'),
                ('Can I add old dues from my notebook?',
                 'Yes, add the customer with the previous due and tracking starts.'),
                ('Do customers see their due?',
                 'Reminder SMS include their name and amount, so they know what to pay.'),
            ],
        },
    },
    {
        'slug': 'inventory', 'icon': 'bi-boxes', 'image': 'dashboard', 'image_en': 'dashboard',
        'related': ['pos-software', 'accounting', 'online-shop', 'due-book'],
        'bn': {
            'nav': 'স্টক ও ইনভেন্টরি',
            'title': 'ইনভেন্টরি সফটওয়্যার — স্টক, সাইজ-রং, বারকোড, মাল কেনা',
            'description': 'দোকান আর অনলাইনের এক স্টক: সাইজ-রং ধরে আলাদা স্টক, বারকোড স্টিকার, সাপ্লায়ার থেকে মাল কেনা আর বাকি, '
                           'গড় কেনা দাম নিজে থেকে। ৩০ দিন ফ্রি।',
            'h1': '<em>স্টক আর ইনভেন্টরি</em> — দোকান আর অনলাইনে এক হিসাব',
            'lead': 'দোকানে বিক্রি হলে আর ওয়েবসাইটে অর্ডার এলে একই স্টক থেকে কমে। মাল কিনলে স্টক বাড়ে, গড় কেনা দামও ঠিক হয় — '
                    'তাই প্রতিটা প্রোডাক্টে কত লাভ, সেটাও সঠিক।',
            'points': [
                ('bi-grid-3x3-gap-fill', 'সাইজ ও রং (ভ্যারিয়েন্ট)',
                 'M/L/XL বা লাল/নীল — প্রতিটার আলাদা দাম, স্টক আর বারকোড।'),
                ('bi-upc', 'বারকোড স্টিকার',
                 'স্টিকার ছাপিয়ে প্রোডাক্টে লাগান, POS-এ স্ক্যান করে বিক্রি।'),
                ('bi-cart-plus-fill', 'মাল কেনার খাতা',
                 'কোন সাপ্লায়ার থেকে কত দামে কী কিনলেন — স্টক বাড়ে, সাপ্লায়ারের বাকিও হিসাবে থাকে।'),
                ('bi-arrow-left-right', 'দোকান আর অনলাইনের এক স্টক',
                 'POS আর ওয়েবসাইট একই স্টক দেখে; স্টক শেষ হলে ওয়েবসাইটে "স্টক নেই" দেখায়।'),
                ('bi-arrow-counterclockwise', 'রিটার্নে স্টক ফেরত',
                 'বাতিল বা ফেরত এলে স্টক নিজে থেকে আবার যোগ হয়।'),
                ('bi-file-earmark-excel-fill', 'Excel-এ সব',
                 'প্রোডাক্ট, স্টক, মাল কেনা — যেকোনো সময় Excel-এ নামান।'),
            ],
            'faq': [
                ('ইনভেন্টরি সফটওয়্যার আর POS কি আলাদা?',
                 'SellPunch-এ একসাথে — POS-এ বিক্রি, ওয়েবসাইটে অর্ডার, মাল কেনা, সব একই স্টক থেকে।'),
                ('কতগুলো প্রোডাক্ট রাখা যায়?',
                 'Basic-এ ২০০টা, Standard-এ ১,০০০টা, Premium-এ যত খুশি।'),
                ('পুরনো স্টক একসাথে তোলা যায়?',
                 'হ্যাঁ, CSV ফাইল থেকে অনেক প্রোডাক্ট একসাথে তোলা যায়; একটা একটা তুলতেও প্রতিটায় এক মিনিটের মতো।'),
                ('সাপ্লায়ারের বাকি রাখা যায়?',
                 'হ্যাঁ, মাল কেনার সময় কত দিলেন লিখলে বাকিটা সাপ্লায়ারের খাতায় থাকে; পরে টাকা দিলে কমে।'),
            ],
        },
        'en': {
            'nav': 'Stock & inventory',
            'title': 'Inventory Software in Bangladesh — Stock, Variants and Barcodes',
            'description': 'One stock for your shop and online store: separate stock per size and colour, barcode stickers, '
                           'supplier purchases and dues, average cost price calculated. 30 days free.',
            'h1': '<em>Stock and inventory</em> — one count for the shop and online',
            'lead': 'Counter sales and website orders come out of the same stock. Purchases add stock and update the average cost — '
                    'so the profit on every product is right.',
            'points': [
                ('bi-grid-3x3-gap-fill', 'Sizes and colours (variants)',
                 'M/L/XL or red/blue — each with its own price, stock and barcode.'),
                ('bi-upc', 'Barcode stickers',
                 'Print stickers, put them on products and scan to sell at the POS.'),
                ('bi-cart-plus-fill', 'Purchase book',
                 'What you bought from which supplier at what price — stock goes up and supplier dues are tracked.'),
                ('bi-arrow-left-right', 'One stock for shop and online',
                 'POS and website share stock; sold-out items show "out of stock" online.'),
                ('bi-arrow-counterclockwise', 'Returns back to stock',
                 'Cancelled or returned items are added back automatically.'),
                ('bi-file-earmark-excel-fill', 'Everything in Excel',
                 'Download products, stock and purchases to Excel any time.'),
            ],
            'faq': [
                ('Are inventory and POS separate?',
                 'Not in SellPunch — POS sales, website orders and purchases all use the same stock.'),
                ('How many products can I add?',
                 '200 on Basic, 1,000 on Standard and unlimited on Premium.'),
                ('Can I add my existing stock?',
                 'Yes, import many products at once from a CSV file, or add each in about a minute.'),
                ('Can I track supplier dues?',
                 'Yes. Enter what you paid when buying and the rest stays on the supplier account until you pay.'),
            ],
        },
    },
    {
        'slug': 'landing-page', 'icon': 'bi-file-earmark-richtext', 'image': 'landing-phone', 'image_en': 'landing-phone-en',
        'tall': True,
        'related': ['facebook-page-website', 'online-shop', 'courier-integration', 'accounting'],
        'bn': {
            'nav': 'ল্যান্ডিং পেজ',
            'title': 'ল্যান্ডিং পেজ বানান — Facebook বিজ্ঞাপনের জন্য এক প্রোডাক্টের পাতা',
            'description': 'এক প্রোডাক্টের বিক্রির পাতা: শিরোনাম, সুবিধা, অফার আর সাথেই অর্ডার ফর্ম। Facebook বিজ্ঞাপনের লিংক দিন, '
                           'কত ভিউ থেকে কত অর্ডার তা-ও দেখুন। ৩০ দিন ফ্রি।',
            'h1': 'Facebook বিজ্ঞাপনের জন্য <em>ল্যান্ডিং পেজ</em> — ডেভেলপার ছাড়া, কয়েক মিনিটে',
            'lead': 'বিজ্ঞাপনে ক্লিক করে কাস্টমার পুরো দোকানে হারিয়ে যায় না — সোজা ওই প্রোডাক্টের পাতায় আসে, সুবিধা পড়ে, '
                    'নিচেই নাম-ঠিকানা লিখে অর্ডার দেয়।',
            'points': [
                ('bi-type-h1', 'শিরোনাম, সুবিধা, অফার',
                 'বড় শিরোনাম, ছোট বিবরণ, সুবিধার তালিকা আর অফারের লেখা — নিজের মতো লিখুন।'),
                ('bi-bag-check-fill', 'পাতাতেই অর্ডার ফর্ম',
                 'আলাদা চেকআউটে যেতে হয় না; নাম, মোবাইল, ঠিকানা লিখে অর্ডার।'),
                ('bi-bar-chart-fill', 'ভিউ আর অর্ডার',
                 'কতজন পাতা দেখল আর কতজন অর্ডার দিল — কোন বিজ্ঞাপন কাজ করছে বোঝা যায়।'),
                ('bi-collection-fill', '৩০টা পর্যন্ত পাতা',
                 'প্রতিটা প্রোডাক্ট বা অফারের আলাদা পাতা, আলাদা লিংক।'),
                ('bi-star-fill', 'রিভিউ দেখানো',
                 'অনুমোদন দেওয়া রিভিউ পাতায় দেখালে বিশ্বাস বাড়ে।'),
                ('bi-phone', 'মোবাইলে দ্রুত খোলে',
                 'বিজ্ঞাপনের বেশিরভাগ কাস্টমার ফোনে — পাতা হালকা, দ্রুত খোলে।'),
            ],
            'faq': [
                ('ল্যান্ডিং পেজ আর ওয়েবসাইটের পার্থক্য কী?',
                 'ওয়েবসাইটে সব প্রোডাক্ট থাকে; ল্যান্ডিং পেজে শুধু একটা প্রোডাক্ট আর অর্ডার ফর্ম — বিজ্ঞাপন থেকে আসা '
                 'কাস্টমার অন্য দিকে না গিয়ে অর্ডার দেয়।'),
                ('ল্যান্ডিং পেজের জন্য আলাদা টাকা লাগে?',
                 'না, SellPunch-এর প্যাকেজেই আছে — ৩০টা পর্যন্ত পাতা।'),
                ('অর্ডার কোথায় আসে?',
                 'বাকি অর্ডারের মতোই ড্যাশবোর্ডে — সেখান থেকে কনফার্ম করে এক ক্লিকে কুরিয়ারে।'),
                ('কোড লাগবে?',
                 'না, ফর্মে লেখা বসালেই পাতা তৈরি।'),
            ],
        },
        'en': {
            'nav': 'Landing pages',
            'title': 'Landing Page Builder for Facebook Ads — One-Product Sales Pages',
            'description': 'A sales page for one product: headline, benefits, offer and an order form on the same page. Use it in '
                           'Facebook ads and see views and orders. 30 days free.',
            'h1': '<em>Landing pages</em> for Facebook ads — no developer, in minutes',
            'lead': 'Ad clicks do not get lost in the whole store — they land on that product, read the benefits and order right below.',
            'points': [
                ('bi-type-h1', 'Headline, benefits, offer',
                 'Big headline, short description, benefit list and offer text — written your way.'),
                ('bi-bag-check-fill', 'Order form on the page',
                 'No separate checkout; name, mobile, address and done.'),
                ('bi-bar-chart-fill', 'Views and orders',
                 'See how many viewed and how many ordered — know which ad works.'),
                ('bi-collection-fill', 'Up to 30 pages',
                 'A separate page and link for every product or offer.'),
                ('bi-star-fill', 'Show reviews',
                 'Approved reviews on the page build trust.'),
                ('bi-phone', 'Fast on mobile',
                 'Most ad visitors are on phones — pages are light and load fast.'),
            ],
            'faq': [
                ('What is the difference between a landing page and a website?',
                 'A website has every product; a landing page has one product and an order form, so ad visitors order instead of wandering.'),
                ('Do landing pages cost extra?',
                 'No, they are included in SellPunch plans — up to 30 pages.'),
                ('Where do orders go?',
                 'To your dashboard like other orders — confirm and send to the courier in one click.'),
                ('Do I need code?',
                 'No, fill in the form and the page is ready.'),
            ],
        },
    },
    {
        'slug': 'accounting', 'icon': 'bi-graph-up-arrow', 'image': 'reports', 'image_en': 'reports',
        'related': ['pos-software', 'due-book', 'inventory', 'courier-integration'],
        'bn': {
            'nav': 'দোকানের হিসাব',
            'title': 'দোকানের হিসাব সফটওয়্যার — লাভ-লোকসান, খরচ, বাকি এক জায়গায়',
            'description': 'আজ, এই সপ্তাহ, এই মাসে কত বিক্রি, কত লাভ — এক নজরে। নিট লাভ = বিক্রি − কেনা দাম − খরচ। '
                           'খরচের খাতা, সাপ্লায়ারের বাকি, Excel রিপোর্ট। ৩০ দিন ফ্রি।',
            'h1': '<em>দোকানের হিসাব</em> — লাভ হচ্ছে না লোকসান, এক নজরে',
            'lead': 'বিক্রি অনেক, কিন্তু মাস শেষে টাকা কোথায় যায়? প্রতিটা বিক্রির কেনা দাম, দোকানের খরচ আর ফেরত মিলিয়ে '
                    'আসল লাভ দেখায় — খাতা, ক্যালকুলেটর আর Excel ছাড়া।',
            'points': [
                ('bi-calendar3', 'আজ, সপ্তাহ, মাস',
                 'যেকোনো সময়ের বিক্রি আর লাভ, আগের সময়ের সাথে তুলনা।'),
                ('bi-calculator-fill', 'আসল নিট লাভ',
                 'বিক্রি − কেনা দাম − খরচ — ফেরত আর বাতিল বাদ দিয়ে।'),
                ('bi-trophy-fill', 'কোন প্রোডাক্টে লাভ বেশি',
                 'বেশি বিক্রি আর বেশি লাভের প্রোডাক্ট আলাদা করে দেখায়।'),
                ('bi-receipt', 'খরচের খাতা',
                 'ভাড়া, বেতন, বুস্ট, প্যাকেজিং — খরচ লিখলে লাভের সাথে মিলে যায়।'),
                ('bi-truck-flatbed', 'সাপ্লায়ার আর মাল কেনা',
                 'কার কাছ থেকে কত কিনলেন, কত বাকি আছে।'),
                ('bi-file-earmark-excel-fill', 'Excel রিপোর্ট',
                 'অর্ডার, প্রোডাক্ট, কাস্টমার, খরচ — আলাদা শিটে নামান।'),
            ],
            'faq': [
                ('দোকানের হিসাব রাখার সেরা উপায় কী?',
                 'বিক্রির সময়েই হিসাব রাখা — POS বা অর্ডারে বিক্রি হলেই রিপোর্টে ওঠে, আলাদা করে খাতায় লিখতে হয় না।'),
                ('বুস্টের খরচ কি লাভ থেকে বাদ যায়?',
                 'হ্যাঁ, খরচের খাতায় বুস্ট লিখলে রিপোর্টের নিট লাভ থেকে বাদ যায়।'),
                ('হিসাবরক্ষকের কাছে দিতে পারব?',
                 'হ্যাঁ, পুরো রিপোর্ট Excel-এ নামিয়ে দিতে পারেন।'),
                ('মোবাইলে দেখা যায়?',
                 'হ্যাঁ, ড্যাশবোর্ড আর রিপোর্ট ফোনের ব্রাউজারেই দেখা যায়।'),
            ],
        },
        'en': {
            'nav': 'Shop accounting',
            'title': 'Shop Accounting Software — Profit, Expenses & Dues in One Place',
            'description': 'Sales and profit for today, this week and this month at a glance. Net profit = sales − cost − expenses. '
                           'Expense book, supplier dues, Excel reports. 30 days free.',
            'h1': '<em>Shop accounting</em> — profit or loss, at a glance',
            'lead': 'Plenty of sales, but where does the money go? Cost prices, shop expenses and returns are matched against every sale '
                    'to show real profit — without notebooks, calculators or Excel.',
            'points': [
                ('bi-calendar3', 'Today, week, month',
                 'Sales and profit for any period, compared with the one before.'),
                ('bi-calculator-fill', 'Real net profit',
                 'Sales − cost − expenses, with returns and cancellations removed.'),
                ('bi-trophy-fill', 'Most profitable products',
                 'Best sellers and best earners shown separately.'),
                ('bi-receipt', 'Expense book',
                 'Rent, salaries, boosts, packaging — expenses flow into profit.'),
                ('bi-truck-flatbed', 'Suppliers and purchases',
                 'What you bought from whom and what you still owe.'),
                ('bi-file-earmark-excel-fill', 'Excel reports',
                 'Orders, products, customers and expenses on separate sheets.'),
            ],
            'faq': [
                ('What is the best way to keep shop accounts?',
                 'Record at the moment of sale — POS and order sales go straight into reports, nothing to copy into a notebook.'),
                ('Are Facebook boost costs taken out of profit?',
                 'Yes, add boosts to the expense book and they come off net profit.'),
                ('Can I give it to my accountant?',
                 'Yes, download the full report to Excel.'),
                ('Can I see it on my phone?',
                 'Yes, the dashboard and reports work in the phone browser.'),
            ],
        },
    },
]

INDUSTRIES = [
    {
        'slug': 'new-business', 'icon': 'bi-rocket-takeoff-fill', 'image': 'dashboard', 'image_en': 'dashboard',
        'phone': 'shop-phone', 'phone_en': 'shop-phone-en',
        'related': ['online-shop', 'facebook-auto-reply', 'courier-integration', 'accounting'],
        'bn': {
            'nav': 'নতুন ব্যবসা শুরু',
            'title': 'অনলাইন ব্যবসা শুরু করবেন? ওয়েবসাইট, অর্ডার, ডেলিভারি — এক জায়গায়',
            'description': 'নতুন অনলাইন ব্যবসা শুরু করতে যা লাগে: ১ মিনিটে নিজের ওয়েবসাইট, ক্যাশ অন ডেলিভারি, কুরিয়ার বুকিং, '
                           'Facebook অটো রিপ্লাই আর লাভের হিসাব। ৩০ দিন ফ্রি।',
            'h1': '<em>অনলাইন ব্যবসা শুরু</em> করতে চান? প্রথম দিন থেকেই গোছানো দোকান',
            'lead': 'প্রোডাক্ট ঠিক করেছেন, Facebook পেজও আছে বা খুলবেন — এবার দরকার এমন একটা জায়গা যেখানে কাস্টমার নিজে দেখে '
                    'অর্ডার করবে, আর আপনি অর্ডার, ডেলিভারি আর টাকার হিসাব এক জায়গায় দেখবেন। SellPunch-এ সেটা ১ মিনিটে চালু হয়, '
                    'ডেভেলপার বা হোস্টিং ছাড়া।',
            'points': [
                ('bi-lightning-charge-fill', '১ মিনিটে নিজের ওয়েবসাইট',
                 'দোকানের নাম আর পছন্দের ঠিকানা দিলেই yourshop.sellpunch.com চালু। ডোমেইন, হোস্টিং, ডিজাইনার — কিছুই কিনতে হয় না।'),
                ('bi-facebook', 'Facebook পেজের সাথে',
                 'ওয়েবসাইটের লিংক পেজে দিন। পেজ যুক্ত করলে কমেন্ট আর Messenger-এ দাম-ডেলিভারির উত্তর নিজে থেকে যায় '
                 '(Standard ও Premium)।'),
                ('bi-cash-coin', 'ক্যাশ অন ডেলিভারি থেকেই শুরু',
                 'কাস্টমার পণ্য হাতে পেয়ে টাকা দেবে; চাইলে bKash/Nagad-এ অগ্রিম — শুধু ডেলিভারি চার্জ বা পুরো টাকা।'),
                ('bi-truck', 'কুরিয়ারে এক ক্লিকে',
                 'Steadfast, Pathao বা RedX-এর মার্চেন্ট অ্যাকাউন্ট যুক্ত করলে অর্ডার থেকেই পার্সেল বুক, ট্র্যাকিং কোড নিজে বসে।'),
                ('bi-shield-exclamation', 'ভুয়া অর্ডার থেকে বাঁচা',
                 'যে নম্বর আগে পার্সেল ফেরত দিয়েছে তার অর্ডারের পাশে সতর্কতা; চাইলে নম্বরটা ব্লক করে রাখুন।'),
                ('bi-graph-up-arrow', 'শুরু থেকেই লাভের হিসাব',
                 'কেনা দাম আর খরচ (বুস্ট, প্যাকেজিং) লিখলে আসল লাভ দেখায় — কোন প্রোডাক্টে লাভ বেশি।'),
                ('bi-phone', 'শুধু মোবাইল দিয়েই',
                 'কম্পিউটার লাগে না, অ্যাপ ইনস্টলও না — ফোনের ব্রাউজারেই সব।'),
                ('bi-shop', 'পরে দোকান খুললেও একই সফটওয়্যার',
                 'দোকান বা শোরুম দিলে POS-এ বারকোড স্ক্যান করে বিল — ওয়েবসাইট আর দোকানের স্টক এক।'),
            ],
            'steps': [
                ('প্রোডাক্ট আর দাম ঠিক করুন', 'কী বিক্রি করবেন, কেনা দাম কত, কত টাকায় বেচবেন — প্রোডাক্টের ভালো ছবি তুলে রাখুন।'),
                ('১ মিনিটে ওয়েবসাইট খুলুন', 'দোকানের নাম আর ঠিকানা দিয়ে অ্যাকাউন্ট খুলুন, প্রোডাক্ট তুলুন, ডেলিভারি চার্জ ঠিক করুন।'),
                ('লিংক ছড়িয়ে দিন', 'Facebook পেজ, পোস্ট আর WhatsApp-এ লিংক দিন। অর্ডার এলে কনফার্ম করে কুরিয়ারে পাঠান।'),
            ],
            'faq': [
                ('অনলাইন ব্যবসা শুরু করতে কী কী লাগে?',
                 'বিক্রির মতো প্রোডাক্ট, ভালো ছবি, একটা মোবাইল, আর এমন জায়গা যেখানে কাস্টমার দেখে অর্ডার করবে — সাধারণত '
                 'Facebook পেজ আর নিজের ওয়েবসাইট। ডেলিভারির জন্য একটা কুরিয়ারের মার্চেন্ট অ্যাকাউন্ট। SellPunch-এ ওয়েবসাইট, '
                 'অর্ডার, কুরিয়ার বুকিং, Facebook অটো রিপ্লাই আর হিসাব এক জায়গায় পাবেন।'),
                ('শুরুতে কত টাকা লাগবে?',
                 'SellPunch-এ প্রথম ৩০ দিন ফ্রি, তারপর মাসে ৪৯৯ টাকা থেকে — ডোমেইন বা হোস্টিং আলাদা কিনতে হয় না। বাকি খরচ '
                 'আপনার প্রোডাক্ট, প্যাকেজিং আর বিজ্ঞাপনের।'),
                ('শুধু Facebook পেজ দিয়ে ব্যবসা করলে সমস্যা কী?',
                 'পেজে প্রোডাক্ট খুঁজতে কাস্টমারকে পোস্ট ঘাঁটতে হয়, প্রতিটা দাম ইনবক্সে বলতে হয়, আর অর্ডার খাতায় লিখে রাখতে হয়। '
                 'ওয়েবসাইটে কাস্টমার নিজে অর্ডার করে, অর্ডার হারায় না, আর পেজের পাশে নিজের ওয়েবসাইট থাকলে কাস্টমার বেশি বিশ্বাস করে।'),
                ('ওয়েবসাইট বানানো না জানলে চলবে?',
                 'হ্যাঁ। কোড বা ডিজাইন জানতে হয় না — ৪টা তৈরি ডিজাইন থেকে একটা বাছুন, লোগো আর ব্যানার দিন। Facebook চালাতে '
                 'পারলেই পারবেন।'),
                ('ট্রেড লাইসেন্স ছাড়া শুরু করা যায়?',
                 'SellPunch-এ সাইনআপের জন্য ট্রেড লাইসেন্স লাগে না; ব্যবসা বড় হলে আইন অনুযায়ী লাইসেন্স করে নেওয়া ভালো।'),
                ('কেনার আগে দেখে নেওয়া যায়?',
                 'হ্যাঁ — লাইভ ডেমো দোকানে ঢুকে পুরো ড্যাশবোর্ড চালিয়ে দেখুন, অ্যাকাউন্ট খুলতে হয় না।'),
            ],
        },
        'en': {
            'nav': 'Starting a business',
            'title': 'Start an Online Business in Bangladesh — Website, Orders, Delivery',
            'description': 'Start an online business in Bangladesh: your website in 1 minute, cash on delivery, courier booking, '
                           'Facebook auto reply and profit tracking. 30 days free.',
            'h1': 'Want to <em>start an online business</em>? Be organised from day one',
            'lead': 'You have your products, and a Facebook page or the plan to open one. Now you need a place where customers '
                    'browse and order on their own, and where you see orders, deliveries and money in one place. On SellPunch '
                    'it is live in 1 minute, without a developer or hosting.',
            'points': [
                ('bi-lightning-charge-fill', 'Your website in 1 minute',
                 'Enter a shop name and the address you want and yourshop.sellpunch.com is live. No domain, hosting or designer to buy.'),
                ('bi-facebook', 'Works with your Facebook page',
                 'Put the website link on your page. Connect the page and comment and Messenger questions about price and '
                 'delivery are answered automatically (Standard and Premium).'),
                ('bi-cash-coin', 'Start with cash on delivery',
                 'Customers pay when they receive the product; or take bKash/Nagad advance — just the delivery charge or the full amount.'),
                ('bi-truck', 'Courier in one click',
                 'Connect your Steadfast, Pathao or RedX merchant account and book parcels from the order; the tracking code fills in itself.'),
                ('bi-shield-exclamation', 'Avoid fake orders',
                 'Numbers that returned parcels before get a warning next to their order; block a number if you want.'),
                ('bi-graph-up-arrow', 'Profit from the start',
                 'Add buying prices and costs (boosts, packaging) to see real profit — and which products earn the most.'),
                ('bi-phone', 'Just your phone',
                 'No computer and no app to install — everything works in the phone browser.'),
                ('bi-shop', 'Same software when you open a shop',
                 'Open a shop or showroom later and bill with the barcode POS — website and shop share one stock.'),
            ],
            'steps': [
                ('Decide products and prices', 'What you will sell, what it costs you and your selling price — take good product photos.'),
                ('Open your website in 1 minute', 'Sign up with a shop name and address, add products and set delivery charges.'),
                ('Share your link', 'Post it on your Facebook page, in posts and on WhatsApp. Confirm orders and send them by courier.'),
            ],
            'faq': [
                ('What do I need to start an online business in Bangladesh?',
                 'Products worth selling, good photos, a phone, and a place where customers can see and order — usually a Facebook '
                 'page and your own website — plus a courier merchant account for delivery. SellPunch gives you the website, orders, '
                 'courier booking, Facebook auto reply and accounts in one place.'),
                ('How much money do I need to start?',
                 'SellPunch is free for the first 30 days, then from BDT 499 a month — no separate domain or hosting. The rest '
                 'is your products, packaging and ads.'),
                ('What is wrong with selling only through a Facebook page?',
                 'On a page, customers scroll through posts to find products, ask every price in the inbox, and orders get written '
                 'in a notebook. On a website customers order themselves, orders are not lost, and a website next to your page '
                 'earns more trust.'),
                ('Can I do it without knowing how to build websites?',
                 'Yes. No code or design skills — pick one of 4 ready-made designs and add your logo and banner. If you can use '
                 'Facebook you can use SellPunch.'),
                ('Can I start without a trade licence?',
                 'Signing up to SellPunch does not need a trade licence; as the business grows, getting one under the law is wise.'),
                ('Can I try it before paying?',
                 'Yes — open the live demo shop and use the whole dashboard, no account needed.'),
            ],
        },
    },
    {
        'slug': 'clothing', 'icon': 'bi-handbag-fill', 'image': 'design-bold', 'image_en': 'design-bold-en', 'image_w': 1200,
        'related': ['online-shop', 'inventory', 'facebook-page-website', 'courier-integration'],
        'bn': {
            'nav': 'পোশাক ও ফ্যাশন',
            'title': 'পোশাকের দোকানের ওয়েবসাইট আর POS — সাইজ-রং ধরে স্টক',
            'description': 'থ্রি-পিস, শাড়ি, পাঞ্জাবি, টি-শার্টের অনলাইন শপ ১ মিনিটে। সাইজ-রং ধরে আলাদা স্টক, কুরিয়ার বুকিং, '
                           'দোকানের POS আর বাকির খাতা। ৩০ দিন ফ্রি।',
            'h1': '<em>পোশাকের দোকানের</em> ওয়েবসাইট — প্রতিটা সাইজ আর রঙের আলাদা স্টক',
            'lead': 'থ্রি-পিস, শাড়ি, পাঞ্জাবি বা টি-শার্ট — কাস্টমার ওয়েবসাইটে সাইজ আর রং বেছে অর্ডার দেয়, শেষ হওয়া সাইজ নিজে থেকে '
                    '"স্টক নেই" দেখায়। দোকানে বিক্রি হলেও একই স্টক কমে।',
            'points': [
                ('bi-grid-3x3-gap-fill', 'সাইজ-রং ধরে স্টক', 'M/L/XL বা লাল/নীল — প্রতিটার আলাদা দাম আর স্টক।'),
                ('bi-card-text', 'কাপড় আর মাপের বিবরণ', 'প্রোডাক্টের বিবরণে কাপড়, মাপ আর যত্নের নিয়ম — কাস্টমার অর্ডারের আগে পড়ে নেয়।'),
                ('bi-truck', 'এক ক্লিকে কুরিয়ার', 'Steadfast, Pathao বা RedX — অর্ডার থেকেই পার্সেল বুক।'),
                ('bi-ticket-perforated-fill', 'ঈদ আর পূজার অফার', 'কুপন কোড আর ফ্রি ডেলিভারির শর্ত, নির্দিষ্ট সময়ের জন্য।'),
                ('bi-upc-scan', 'দোকানে POS', 'শোরুমে বারকোড স্ক্যান করে বিল, রসিদ প্রিন্ট।'),
                ('bi-arrow-counterclockwise', 'সাইজ বদল আর ফেরত', 'ফেরত এলে স্টক আবার যোগ হয়, হিসাব থেকে বাদ যায়।'),
            ],
            'faq': [
                ('অনলাইনে কাপড়ের ব্যবসা শুরু করতে ওয়েবসাইট লাগবে?',
                 'Facebook পেজ দিয়ে শুরু করা যায়, কিন্তু অর্ডার বাড়লে ইনবক্সে সাইজ-রং মেলানো কঠিন হয়। ওয়েবসাইটে কাস্টমার নিজে '
                 'বেছে অর্ডার দেয়, স্টকও মেলে।'),
                ('এক ডিজাইনের অনেক সাইজ-রং থাকলে?',
                 'একটা প্রোডাক্টেই সব সাইজ-রং যোগ করুন; প্রতিটার আলাদা স্টক, চাইলে আলাদা দাম।'),
                ('পাইকারি দামে বিক্রি করা যায়?',
                 'POS-এ বিলের সময় ছাড় দেওয়া যায়; ওয়েবসাইটে কুপন কোড দিয়েও।'),
            ],
        },
        'en': {
            'nav': 'Clothing & fashion',
            'title': 'Clothing Store Website & POS in Bangladesh — Stock by Size and Colour',
            'description': 'An online store for three-pieces, sarees, panjabis and t-shirts in 1 minute. Stock per size and colour, '
                           'courier booking, shop POS and due book. 30 days free.',
            'h1': 'A <em>clothing store</em> website — separate stock for every size and colour',
            'lead': 'Three-pieces, sarees, panjabis or t-shirts — customers pick size and colour and order; sold-out sizes show '
                    '"out of stock" by themselves. Shop sales come out of the same stock.',
            'points': [
                ('bi-grid-3x3-gap-fill', 'Stock by size and colour', 'M/L/XL or red/blue — each with its own price and stock.'),
                ('bi-card-text', 'Fabric and size details', 'Fabric, measurements and care in the description — read before ordering.'),
                ('bi-truck', 'One-click courier', 'Steadfast, Pathao or RedX — book straight from the order.'),
                ('bi-ticket-perforated-fill', 'Eid and Puja offers', 'Coupon codes and free-delivery rules for a set time.'),
                ('bi-upc-scan', 'POS in the shop', 'Scan barcodes in the showroom and print receipts.'),
                ('bi-arrow-counterclockwise', 'Exchanges and returns', 'Returns go back into stock and out of sales.'),
            ],
            'faq': [
                ('Do I need a website to sell clothes online?',
                 'You can start with a Facebook page, but matching sizes and colours in the inbox gets hard as orders grow. '
                 'On a website customers choose and order themselves, and stock stays right.'),
                ('One design in many sizes and colours?',
                 'Add all sizes and colours to one product, each with its own stock and price if you like.'),
                ('Can I sell at wholesale prices?',
                 'Give discounts on the POS bill, or use coupon codes on the website.'),
            ],
        },
    },
    {
        'slug': 'cosmetics', 'icon': 'bi-droplet-half', 'image': 'design-soft', 'image_en': 'design-soft-en', 'image_w': 1200,
        'related': ['online-shop', 'landing-page', 'facebook-page-website', 'courier-integration'],
        'bn': {
            'nav': 'কসমেটিকস ও স্কিনকেয়ার',
            'title': 'কসমেটিকস ও স্কিনকেয়ার শপের ওয়েবসাইট — অরিজিনাল প্রোডাক্টে বিশ্বাস',
            'description': 'কসমেটিকস, স্কিনকেয়ার আর বিউটি প্রোডাক্টের অনলাইন শপ ১ মিনিটে। যাচাই করা রিভিউ, ল্যান্ডিং পেজ, '
                           'bKash অগ্রিম, কুরিয়ার বুকিং। ৩০ দিন ফ্রি।',
            'h1': '<em>কসমেটিকস আর স্কিনকেয়ারের</em> অনলাইন শপ — রিভিউ দেখে কিনবে কাস্টমার',
            'lead': 'বিউটি প্রোডাক্টে কাস্টমার আগে বিশ্বাস খোঁজে। প্রতিটা প্রোডাক্টের পরিষ্কার ছবি, বিবরণ আর যাচাই করা ক্রেতার রিভিউ '
                    'এক পাতায় — Facebook বিজ্ঞাপনের জন্য আলাদা ল্যান্ডিং পেজও।',
            'points': [
                ('bi-star-fill', 'যাচাই করা রিভিউ', 'যে নম্বরে প্রোডাক্ট ডেলিভারি হয়েছে, তার রিভিউতে "যাচাই করা ক্রেতা" চিহ্ন; আপনি অনুমোদন দিলে দেখায়।'),
                ('bi-file-earmark-richtext', 'বিজ্ঞাপনের ল্যান্ডিং পেজ', 'এক প্রোডাক্টের পাতা আর অর্ডার ফর্ম — কত ভিউ থেকে কত অর্ডার।'),
                ('bi-wallet2', 'bKash/Nagad অগ্রিম', 'ভুয়া অর্ডার কমাতে শুধু ডেলিভারি চার্জ বা পুরো টাকা অগ্রিম।'),
                ('bi-shield-exclamation', 'ভুয়া অর্ডার চেনা', 'আগে পার্সেল ফেরত দেওয়া নম্বরে সতর্কতা।'),
                ('bi-chat-left-text-fill', 'পুরনো কাস্টমারকে SMS', 'নতুন কালেকশন বা অফারের খবর এক ক্লিকে।'),
                ('bi-ticket-perforated-fill', 'কম্বো আর অফার', 'কুপন কোড, নির্দিষ্ট টাকার উপরে ফ্রি ডেলিভারি।'),
            ],
            'faq': [
                ('কসমেটিকসের অনলাইন ব্যবসায় ভুয়া অর্ডার কমাব কীভাবে?',
                 'অগ্রিম ডেলিভারি চার্জ নেওয়া আর আগে ফেরত দেওয়া নম্বর চেনা — দুটোই SellPunch-এ আছে।'),
                ('বিজ্ঞাপনের জন্য আলাদা পাতা বানানো যায়?',
                 'হ্যাঁ, প্রতিটা প্রোডাক্টের ল্যান্ডিং পেজ — ৩০টা পর্যন্ত।'),
                ('ভুয়া রিভিউ আটকাব কীভাবে?',
                 'আপনি অনুমোদন না দিলে কোনো রিভিউ দেখায় না, আর যে নম্বরে প্রোডাক্ট ডেলিভারি হয়েছে তার রিভিউতে "যাচাই করা ক্রেতা" চিহ্ন থাকে।'),
            ],
        },
        'en': {
            'nav': 'Cosmetics & skincare',
            'title': 'Cosmetics & Skincare Store Website — Build Trust in Original Products',
            'description': 'An online store for cosmetics, skincare and beauty products in 1 minute. Verified reviews, landing pages, '
                           'bKash advance, courier booking. 30 days free.',
            'h1': 'A <em>cosmetics and skincare</em> store — customers buy after reading reviews',
            'lead': 'Beauty buyers look for trust first. Clear photos, details and verified-buyer reviews on one page — and separate '
                    'landing pages for Facebook ads.',
            'points': [
                ('bi-star-fill', 'Verified reviews', 'Reviews from numbers that received the product get a "verified buyer" mark; shown when you approve.'),
                ('bi-file-earmark-richtext', 'Ad landing pages', 'One product and an order form — see views and orders.'),
                ('bi-wallet2', 'bKash/Nagad advance', 'Take the delivery charge or full amount in advance to cut fake orders.'),
                ('bi-shield-exclamation', 'Spot fake orders', 'Warnings for numbers that returned parcels before.'),
                ('bi-chat-left-text-fill', 'SMS to past buyers', 'New collection or offer news in one click.'),
                ('bi-ticket-perforated-fill', 'Combos and offers', 'Coupon codes and free delivery above an amount.'),
            ],
            'faq': [
                ('How do I reduce fake orders in an online cosmetics business?',
                 'Take the delivery charge in advance and watch for numbers that returned parcels before — SellPunch does both.'),
                ('Can I make separate pages for ads?',
                 'Yes, a landing page per product — up to 30.'),
                ('How do I keep out fake reviews?',
                 'No review shows until you approve it, and reviews from numbers that received the product carry a "verified buyer" mark.'),
            ],
        },
    },
    {
        'slug': 'gadgets', 'icon': 'bi-phone-fill', 'image': 'design-minimal', 'image_en': 'design-minimal-en', 'image_w': 1200,
        'related': ['pos-software', 'inventory', 'online-shop', 'due-book'],
        'bn': {
            'nav': 'মোবাইল ও গ্যাজেট',
            'title': 'মোবাইল ও গ্যাজেট দোকানের সফটওয়্যার — POS, ওয়েবসাইট, স্টক',
            'description': 'মোবাইল, এক্সেসরিজ আর ইলেকট্রনিক্স দোকানের জন্য POS, অনলাইন শপ আর স্টক। বারকোড, রসিদ, বাকি, '
                           'অগ্রিম পেমেন্ট, কুরিয়ার। ৩০ দিন ফ্রি।',
            'h1': '<em>মোবাইল আর গ্যাজেট দোকানের</em> সফটওয়্যার — দোকান আর অনলাইনে এক হিসাব',
            'lead': 'চার্জার থেকে হেডফোন, ফোন থেকে স্মার্টওয়াচ — শোরুমে বারকোড স্ক্যান করে বিল, আর একই প্রোডাক্ট ওয়েবসাইটে বিক্রি। '
                    'দামি প্রোডাক্টে অগ্রিম পেমেন্ট নিয়ে নিশ্চিন্ত।',
            'points': [
                ('bi-upc-scan', 'বারকোড আর রসিদ', 'স্ক্যান করে বিল, লোগো আর ফেরতের নিয়মসহ রসিদ।'),
                ('bi-grid-3x3-gap-fill', 'মডেল আর রং', 'একই প্রোডাক্টের ভিন্ন মডেল বা রং, আলাদা দাম আর স্টক।'),
                ('bi-wallet2', 'অগ্রিম পেমেন্ট', 'দামি প্রোডাক্টে bKash, Nagad বা কার্ডে পুরো টাকা আগে।'),
                ('bi-journal-text', 'বাকি আর কিস্তির হিসাব', 'বাকিতে দিলে খাতায় ওঠে, আংশিক জমা লেখা যায়।'),
                ('bi-cart-plus-fill', 'মাল কেনা আর সাপ্লায়ার', 'কোন সাপ্লায়ার থেকে কত দামে, কত বাকি।'),
                ('bi-graph-up-arrow', 'প্রোডাক্ট ধরে লাভ', 'কোন প্রোডাক্টে লাভ বেশি — রিপোর্টে।'),
            ],
            'faq': [
                ('মোবাইল দোকানে কোন POS সফটওয়্যার ভালো?',
                 'যেটায় বিক্রি, স্টক, বাকি আর অনলাইন অর্ডার এক জায়গায় — SellPunch-এ সব একসাথে, বাংলায়।'),
                ('অনলাইনে দামি জিনিস বিক্রিতে ঝুঁকি কমাব কীভাবে?',
                 'পুরো টাকা অগ্রিম নেওয়ার নিয়ম রাখুন; কাস্টমার bKash, Nagad বা কার্ডে দেবে।'),
                ('একাধিক স্টাফ বিল করতে পারবে?',
                 'হ্যাঁ, প্রত্যেকের আলাদা লগইন — Standard-এ ৩, Premium-এ ১০ জন।'),
            ],
        },
        'en': {
            'nav': 'Mobile & gadgets',
            'title': 'Mobile & Gadget Shop Software — POS, Website and Stock',
            'description': 'POS, online store and stock for mobile, accessories and electronics shops. Barcodes, receipts, dues, '
                           'advance payment, courier. 30 days free.',
            'h1': 'Software for <em>mobile and gadget shops</em> — one count for the shop and online',
            'lead': 'Chargers to headphones, phones to smartwatches — scan and bill in the showroom and sell the same products online. '
                    'Take advance payment on expensive items.',
            'points': [
                ('bi-upc-scan', 'Barcodes and receipts', 'Scan to bill; receipts with your logo and return policy.'),
                ('bi-grid-3x3-gap-fill', 'Models and colours', 'Different models or colours of one product, each priced and stocked.'),
                ('bi-wallet2', 'Advance payment', 'Full payment first with bKash, Nagad or card for expensive items.'),
                ('bi-journal-text', 'Dues and part payments', 'Credit sales go to the due book; record part payments.'),
                ('bi-cart-plus-fill', 'Purchases and suppliers', 'From which supplier, at what price, and what is owed.'),
                ('bi-graph-up-arrow', 'Profit per product', 'See which products earn the most.'),
            ],
            'faq': [
                ('Which POS software is good for a mobile shop?',
                 'One that keeps sales, stock, dues and online orders together — SellPunch does, in Bangla.'),
                ('How do I lower the risk of selling expensive items online?',
                 'Require full advance payment; customers pay with bKash, Nagad or card.'),
                ('Can several staff bill?',
                 'Yes, each with their own login — 3 on Standard, 10 on Premium.'),
            ],
        },
    },
    {
        'slug': 'grocery', 'icon': 'bi-basket2-fill', 'image': 'pos', 'image_en': 'pos',
        'related': ['pos-software', 'due-book', 'inventory', 'accounting'],
        'bn': {
            'nav': 'মুদি দোকান ও সুপারশপ',
            'title': 'মুদি দোকানের সফটওয়্যার — POS, বাকির খাতা আর হোম ডেলিভারি',
            'description': 'মুদি দোকান আর সুপারশপের জন্য POS: বারকোড স্ক্যান, রসিদ, বাকির খাতা আর তাগাদার SMS, স্টক, '
                           'আর এলাকায় হোম ডেলিভারির ওয়েবসাইট। ৩০ দিন ফ্রি।',
            'h1': '<em>মুদি দোকান আর সুপারশপের</em> সফটওয়্যার — বিল, বাকি আর স্টক',
            'lead': 'সারাদিনের ভিড়ে দ্রুত বিল, চেনা কাস্টমারের বাকি আর মাস শেষে কার কাছে কত পাবেন — সব এক জায়গায়। চাইলে আশেপাশের '
                    'কাস্টমার ওয়েবসাইট থেকে অর্ডার দিয়ে বাসায় নিতে পারে।',
            'points': [
                ('bi-upc-scan', 'দ্রুত বিল', 'বারকোড স্ক্যান বা নাম লিখে খোঁজা, রসিদ প্রিন্ট।'),
                ('bi-journal-text', 'বাকির খাতা', 'কার কাছে কত, কবে দেবে বলেছে — আর তাগাদার SMS।'),
                ('bi-boxes', 'স্টক', 'বিক্রি হলেই কমে, মাল কিনলেই বাড়ে।'),
                ('bi-house-door-fill', 'হোম ডেলিভারি', 'এলাকার কাস্টমার ওয়েবসাইটে অর্ডার দেয়, ডেলিভারি চার্জ আপনার নিয়মে।'),
                ('bi-receipt', 'খরচ আর লাভ', 'ভাড়া, বেতন লিখলে মাস শেষে আসল লাভ দেখায়।'),
                ('bi-people-fill', 'কর্মচারীর আলাদা লগইন', 'ক্যাশিয়ার শুধু বিল করবে, হিসাব দেখবে না।'),
            ],
            'faq': [
                ('মুদি দোকানে বাকির হিসাব রাখার সহজ উপায়?',
                 'POS-এ বাকিতে বিক্রি করলেই বাকির খাতায় ওঠে; তাগাদার SMS এক ক্লিকে।'),
                ('বারকোড ছাড়া প্রোডাক্ট বিক্রি করা যায়?',
                 'হ্যাঁ, নাম লিখে খুঁজে বিল করা যায়; চাইলে নিজের বারকোড স্টিকার ছাপিয়ে নিন।'),
                ('ইন্টারনেট গেলে কী হবে?',
                 'SellPunch অনলাইনে চলে — তাই দোকানে ইন্টারনেট (মোবাইল ডাটা হলেও) লাগবে।'),
            ],
        },
        'en': {
            'nav': 'Grocery & superstores',
            'title': 'Grocery Shop Software — POS, Due Book and Home Delivery',
            'description': 'POS for grocery shops and superstores: barcode scanning, receipts, due book with reminder SMS, stock, '
                           'and a home-delivery website for your area. 30 days free.',
            'h1': 'Software for <em>grocery shops and superstores</em> — bills, dues and stock',
            'lead': 'Fast billing in the rush, credit for regular customers and who owes what at month end — all in one place. '
                    'Nearby customers can order from your website for home delivery.',
            'points': [
                ('bi-upc-scan', 'Fast billing', 'Scan barcodes or search by name; print receipts.'),
                ('bi-journal-text', 'Due book', 'Who owes what and when they promised — with reminder SMS.'),
                ('bi-boxes', 'Stock', 'Goes down when you sell and up when you buy.'),
                ('bi-house-door-fill', 'Home delivery', 'Local customers order online; delivery charges your way.'),
                ('bi-receipt', 'Expenses and profit', 'Add rent and salaries to see real profit at month end.'),
                ('bi-people-fill', 'Separate staff logins', 'Cashiers bill but cannot see accounts.'),
            ],
            'faq': [
                ('What is an easy way to track dues in a grocery shop?',
                 'Sell on credit at the POS and it goes into the due book; reminder SMS in one click.'),
                ('Can I sell products without barcodes?',
                 'Yes, search by name to bill, or print your own barcode stickers.'),
                ('What if the internet goes down?',
                 'SellPunch runs online, so the shop needs internet (mobile data works).'),
            ],
        },
    },
    {
        'slug': 'books', 'icon': 'bi-book-fill', 'image': 'design-classic', 'image_en': 'design-classic-en', 'image_w': 1200,
        'related': ['online-shop', 'pos-software', 'inventory', 'courier-integration'],
        'bn': {
            'nav': 'বই ও স্টেশনারি',
            'title': 'বই আর স্টেশনারির অনলাইন শপ — ওয়েবসাইট, POS, কুরিয়ার',
            'description': 'বইয়ের দোকান আর অনলাইন বই বিক্রির ওয়েবসাইট ১ মিনিটে। ক্যাটাগরি ধরে সাজানো, প্রি-অর্ডারের মতো '
                           'অগ্রিম, কুরিয়ার বুকিং, দোকানের POS। ৩০ দিন ফ্রি।',
            'h1': '<em>বই আর স্টেশনারির</em> অনলাইন শপ — সারা দেশে কুরিয়ারে',
            'lead': 'লেখক, বিষয় বা শ্রেণি ধরে ক্যাটাগরি সাজান — কাস্টমার খুঁজে অর্ডার দেয়, আপনি এক ক্লিকে কুরিয়ারে পাঠান। '
                    'বইমেলার মৌসুমে অগ্রিম নিয়ে অর্ডার নিশ্চিত।',
            'points': [
                ('bi-tags-fill', 'ক্যাটাগরি', 'লেখক, বিষয়, শ্রেণি — যেভাবে খোঁজে, সেভাবে সাজান।'),
                ('bi-search', 'খোঁজার ব্যবস্থা', 'বইয়ের নাম লিখলেই পায়; Google-এও প্রতিটা বইয়ের আলাদা পাতা।'),
                ('bi-wallet2', 'অগ্রিম পেমেন্ট', 'নতুন বই বা প্রি-অর্ডারে bKash/Nagad-এ অগ্রিম।'),
                ('bi-truck', 'সারা দেশে কুরিয়ার', 'Steadfast, Pathao, RedX — এক ক্লিকে বুক।'),
                ('bi-upc-scan', 'দোকানে POS', 'ISBN বারকোড স্ক্যান করে বিল।'),
                ('bi-chat-left-text-fill', 'নতুন বইয়ের খবর', 'পুরনো ক্রেতাদের এক ক্লিকে SMS।'),
            ],
            'faq': [
                ('অনলাইনে বই বিক্রির জন্য কী লাগে?',
                 'একটা ওয়েবসাইট আর কুরিয়ার অ্যাকাউন্ট — SellPunch-এ ওয়েবসাইট ১ মিনিটে, কুরিয়ার বুকিং এক ক্লিকে।'),
                ('বইয়ের বারকোড (ISBN) দিয়ে বিল করা যায়?',
                 'হ্যাঁ, প্রোডাক্টে বইয়ের বারকোড লিখে রাখলে POS-এ স্ক্যান করলেই আসে।'),
                ('অনেক বই একসাথে কীভাবে তুলব?',
                 'CSV ফাইল থেকে একসাথে তোলা যায়; ক্যাটাগরি আগে বানিয়ে নিলে সাজানো সহজ।'),
            ],
        },
        'en': {
            'nav': 'Books & stationery',
            'title': 'Online Bookstore Website — Website, POS and Courier',
            'description': 'A website for your bookshop or online book business in 1 minute. Categories, advance payment for '
                           'pre-orders, courier booking and shop POS. 30 days free.',
            'h1': 'An <em>online book and stationery</em> store — shipping nationwide',
            'lead': 'Organise by author, subject or class — customers find and order, you ship in one click. Take advance payment '
                    'during book fair season.',
            'points': [
                ('bi-tags-fill', 'Categories', 'Author, subject, class — organised the way people search.'),
                ('bi-search', 'Search', 'Customers type the title; every book has its own Google-friendly page.'),
                ('bi-wallet2', 'Advance payment', 'bKash/Nagad advance for new titles or pre-orders.'),
                ('bi-truck', 'Nationwide courier', 'Steadfast, Pathao, RedX — book in one click.'),
                ('bi-upc-scan', 'POS in the shop', 'Scan ISBN barcodes to bill.'),
                ('bi-chat-left-text-fill', 'New title alerts', 'SMS past buyers in one click.'),
            ],
            'faq': [
                ('What do I need to sell books online?',
                 'A website and a courier account — SellPunch gives you the website in 1 minute and one-click courier booking.'),
                ('Can I bill with ISBN barcodes?',
                 'Yes, save the book barcode on the product and scan it at the POS.'),
                ('How do I add many books?',
                 'Import them from a CSV file; create categories first to keep things tidy.'),
            ],
        },
    },
    {
        'slug': 'home-business', 'icon': 'bi-house-heart-fill', 'image': 'shop-phone', 'image_en': 'shop-phone-en',
        'tall': True,
        'related': ['facebook-page-website', 'online-shop', 'courier-integration', 'accounting'],
        'bn': {
            'nav': 'ঘরে বসে ব্যবসা',
            'title': 'ঘরে বসে অনলাইন ব্যবসা — হোমমেড খাবার, হস্তশিল্পের ওয়েবসাইট',
            'description': 'ঘরে বসে অনলাইন ব্যবসার জন্য নিজের ওয়েবসাইট ১ মিনিটে, মোবাইল থেকেই চালান। হোমমেড খাবার, হস্তশিল্প, '
                           'পোশাক — অর্ডার, কুরিয়ার, হিসাব। ৩০ দিন ফ্রি।',
            'h1': '<em>ঘরে বসে অনলাইন ব্যবসা</em> — নিজের ওয়েবসাইট, পুরোটা মোবাইল থেকে',
            'lead': 'হোমমেড খাবার, আচার, হস্তশিল্প বা নিজের ডিজাইনের পোশাক — Facebook পেজের পাশাপাশি নিজের ওয়েবসাইট থাকলে '
                    'কাস্টমার বিশ্বাস করে। কম্পিউটার লাগে না, ফোনেই সব।',
            'points': [
                ('bi-phone', 'শুধু মোবাইল', 'প্রোডাক্ট তোলা, অর্ডার দেখা, কুরিয়ারে পাঠানো — ফোনের ব্রাউজারে।'),
                ('bi-lightning-charge-fill', '১ মিনিটে ওয়েবসাইট', 'দোকানের নাম আর ঠিকানা দিলেই চালু।'),
                ('bi-cash-coin', 'অগ্রিম বা ক্যাশ অন ডেলিভারি', 'অর্ডারে বানানো জিনিসে অগ্রিম নিন, বাকিগুলোয় COD।'),
                ('bi-whatsapp', 'WhatsApp-এ অর্ডার', 'যে কাস্টমার কথা বলে কিনতে চায়, তার জন্য বাটন।'),
                ('bi-graph-up-arrow', 'লাভের হিসাব', 'কাঁচামাল আর প্যাকেজিংয়ের খরচ লিখলে আসল লাভ।'),
                ('bi-chat-left-text-fill', 'পুরনো কাস্টমারকে SMS', 'নতুন আইটেম বা অফারের খবর।'),
            ],
            'faq': [
                ('ঘরে বসে অনলাইন ব্যবসা শুরু করতে কত টাকা লাগে?',
                 'ওয়েবসাইটের জন্য SellPunch-এ প্রথম ৩০ দিন ফ্রি, তারপর মাসে ৪৯৯ টাকা থেকে। আলাদা ডোমেইন বা হোস্টিং লাগে না।'),
                ('ট্রেড লাইসেন্স ছাড়া ওয়েবসাইট খোলা যায়?',
                 'SellPunch-এ সাইনআপের জন্য ট্রেড লাইসেন্স লাগে না; ব্যবসা বড় হলে আইন অনুযায়ী লাইসেন্স করে নেওয়া ভালো।'),
                ('কম্পিউটার না থাকলে চলবে?',
                 'হ্যাঁ, পুরোটা মোবাইল থেকে চালানো যায়, অ্যাপ ইনস্টল লাগে না।'),
            ],
        },
        'en': {
            'nav': 'Home business',
            'title': 'Home-Based Online Business — Website for Homemade Food & Crafts',
            'description': 'Your own website for a home-based online business in 1 minute, run from your phone. Homemade food, '
                           'crafts, clothing — orders, courier, accounts. 30 days free.',
            'h1': 'A <em>home-based online business</em> — your own website, run from your phone',
            'lead': 'Homemade food, pickles, crafts or your own designs — a website next to your Facebook page earns customer trust. '
                    'No computer needed, everything works on your phone.',
            'points': [
                ('bi-phone', 'Phone only', 'Add products, see orders and ship from the phone browser.'),
                ('bi-lightning-charge-fill', 'Website in 1 minute', 'Enter a shop name and address and it is live.'),
                ('bi-cash-coin', 'Advance or cash on delivery', 'Advance for made-to-order items, COD for the rest.'),
                ('bi-whatsapp', 'WhatsApp orders', 'A button for customers who want to talk first.'),
                ('bi-graph-up-arrow', 'Profit tracking', 'Add ingredient and packaging costs to see real profit.'),
                ('bi-chat-left-text-fill', 'SMS to past buyers', 'News of new items or offers.'),
            ],
            'faq': [
                ('How much does it cost to start an online business from home?',
                 'The website is free for the first 30 days on SellPunch, then from BDT 499 a month. No domain or hosting to buy.'),
                ('Can I open a website without a trade licence?',
                 'Signing up to SellPunch does not need a trade licence; as the business grows, getting one under the law is wise.'),
                ('Do I need a computer?',
                 'No, everything works from your phone, no app to install.'),
            ],
        },
    },
]

KINDS = {'feature': FEATURES, 'industry': INDUSTRIES}
BY_SLUG = {('feature', p['slug']): p for p in FEATURES}
BY_SLUG.update({('industry', p['slug']): p for p in INDUSTRIES})


FACEBOOK_LIVE_CACHE = 'mk:facebook_live'


def facebook_live():
    """Meta-র App Review পাশ করে Facebook অটোমেশন সবার জন্য চালু কিনা (HQ → সেটিংসের সুইচ)। ১ মিনিট মনে রাখে।"""
    from django.core.cache import cache
    value = cache.get(FACEBOOK_LIVE_CACHE)
    if value is None:
        from .models import MasterSetting
        value = bool(MasterSetting.objects.order_by('pk').values_list('facebook_live', flat=True).first())
        cache.set(FACEBOOK_LIVE_CACHE, value, 60)
    return value


def get(kind, slug):
    return BY_SLUG.get((kind, slug))


def all_pages():
    """(kind, page) — sitemap আর llms.txt-এর জন্য।"""
    return [('feature', p) for p in FEATURES] + [('industry', p) for p in INDUSTRIES]
