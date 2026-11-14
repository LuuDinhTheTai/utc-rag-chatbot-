/**
 * Danh sách các ngành nghề trên TopCV
 *
 * Lấy từ: https://www.topcv.vn/viec-lam-moi-nhat
 * Mỗi category có URL riêng với code cr{number}
 */

export const TOPCV_CATEGORIES = [
    {
        id: 'cntt',
        name: 'Công nghệ thông tin',
        url: 'https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257',
        priority: 1, // Ưu tiên cao nhất
    },
    {
        id: 'kinh-doanh',
        name: 'Kinh doanh / Bán hàng',
        url: 'https://www.topcv.vn/tim-viec-lam-kinh-doanh-ban-hang-cr10',
        priority: 2,
    },
    {
        id: 'marketing',
        name: 'Marketing / Truyền thông',
        url: 'https://www.topcv.vn/tim-viec-lam-marketing-truyen-thong-cr11',
        priority: 2,
    },
    {
        id: 'ke-toan',
        name: 'Kế toán / Kiểm toán',
        url: 'https://www.topcv.vn/tim-viec-lam-ke-toan-kiem-toan-cr1',
        priority: 3,
    },
    {
        id: 'nhan-su',
        name: 'Nhân sự',
        url: 'https://www.topcv.vn/tim-viec-lam-nhan-su-cr13',
        priority: 3,
    },
    {
        id: 'hanh-chinh',
        name: 'Hành chính / Văn phòng',
        url: 'https://www.topcv.vn/tim-viec-lam-hanh-chinh-van-phong-cr4',
        priority: 3,
    },
    {
        id: 'thiet-ke',
        name: 'Thiết kế đồ họa / Mỹ thuật',
        url: 'https://www.topcv.vn/tim-viec-lam-thiet-ke-do-hoa-my-thuat-cr22',
        priority: 3,
    },
    {
        id: 'xay-dung',
        name: 'Xây dựng',
        url: 'https://www.topcv.vn/tim-viec-lam-xay-dung-cr25',
        priority: 4,
    },
    {
        id: 'co-khi',
        name: 'Cơ khí / Chế tạo',
        url: 'https://www.topcv.vn/tim-viec-lam-co-khi-che-tao-cr52',
        priority: 4,
    },
    {
        id: 'dien-dien-tu',
        name: 'Điện / Điện tử / Điện lạnh',
        url: 'https://www.topcv.vn/tim-viec-lam-dien-dien-tu-dien-lanh-cr54',
        priority: 4,
    },
    {
        id: 'tai-chinh',
        name: 'Tài chính / Đầu tư',
        url: 'https://www.topcv.vn/tim-viec-lam-tai-chinh-dau-tu-cr17',
        priority: 4,
    },
    {
        id: 'phap-luat',
        name: 'Pháp luật / Pháp lý',
        url: 'https://www.topcv.vn/tim-viec-lam-phap-luat-phap-ly-cr14',
        priority: 4,
    },
    {
        id: 'du-lich',
        name: 'Du lịch / Nhà hàng / Khách sạn',
        url: 'https://www.topcv.vn/tim-viec-lam-du-lich-nha-hang-khach-san-cr3',
        priority: 5,
    },
    {
        id: 'giao-duc',
        name: 'Giáo dục / Đào tạo',
        url: 'https://www.topcv.vn/tim-viec-lam-giao-duc-dao-tao-cr5',
        priority: 5,
    },
    {
        id: 'y-te',
        name: 'Y tế / Dược',
        url: 'https://www.topcv.vn/tim-viec-lam-y-te-duoc-cr26',
        priority: 5,
    },
    {
        id: 'bao-hiem',
        name: 'Bảo hiểm',
        url: 'https://www.topcv.vn/tim-viec-lam-bao-hiem-cr44',
        priority: 5,
    },
    {
        id: 'bao-ve',
        name: 'Bảo vệ / Vệ sĩ / An ninh',
        url: 'https://www.topcv.vn/tim-viec-lam-bao-ve-ve-si-an-ninh-cr45',
        priority: 6,
    },
    {
        id: 'tai-xe',
        name: 'Tài xế / Lái xe',
        url: 'https://www.topcv.vn/tim-viec-lam-tai-xe-lai-xe-cr19',
        priority: 6,
    },
];

/**
 * Lấy categories theo priority
 */
export function getCategoriesByPriority(priority) {
    return TOPCV_CATEGORIES.filter(cat => cat.priority === priority);
}

/**
 * Lấy top N categories
 */
export function getTopCategories(n = 5) {
    return TOPCV_CATEGORIES.slice(0, n);
}

/**
 * Lấy category theo ID
 */
export function getCategoryById(id) {
    return TOPCV_CATEGORIES.find(cat => cat.id === id);
}

/**
 * Lấy tất cả categories
 */
export function getAllCategories() {
    return TOPCV_CATEGORIES;
}
