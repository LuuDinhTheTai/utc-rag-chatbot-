
import * as cheerio from 'cheerio';

const BASE_URL = 'https://www.topcv.vn';

function absoluteUrl(url) {
    if (!url) return null;

    try {
        return new URL(url, BASE_URL).href;
    } catch {
        return null;
    }
}

function cleanText(value) {
    return value?.replace(/\s+/g, ' ').trim() || null;
}

export function parseTopcvJobs(html) {
    const $ = cheerio.load(html);
    const jobs = [];

    $('.job-item-search-result').each((_, element) => {
        const card = $(element);

        const titleLink = card.find('h3.title a').first();
        const companyLink = card.find('a.company').first();

        const logo = card.find('.avatar img').first();

        const tags = [];

        card.find('.box-icon .tag .item-tag').each((_, tag) => {
            const value = cleanText($(tag).text());

            if (value) tags.push(value);
        });

        const remainingTag = card.find(
            '.box-icon .tag .remaining-items'
        ).attr('title');

        jobs.push({
            source: 'topcv',

            externalId: card.attr('data-job-id') || null,

            title: cleanText(titleLink.find('span').first().text())
                || cleanText(titleLink.text()),

            url: absoluteUrl(titleLink.attr('href')),

            company: {
                name: cleanText(
                    companyLink.find('.company-name').text()
                ) || cleanText(companyLink.text()),

                url: absoluteUrl(companyLink.attr('href')),

                logo: absoluteUrl(
                    logo.attr('data-src') || logo.attr('src')
                ),
            },

            salary: cleanText(
                card.find('.info .salary span').first().text()
            ),

            location: cleanText(
                card.find('.address .city-text').first().text()
            ),

            experience: cleanText(
                card.find('.info .exp span').first().text()
            ),

            tags,

            remainingTags: cleanText(remainingTag),

            publishedText: cleanText(
                card.find('.icon label.address').first().text()
            ),
        });
    });

    return jobs;
}
