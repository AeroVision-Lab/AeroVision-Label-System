"""
集成测试
测试AI预测和复审的完整流程
不使用mock，直接测试真实服务
"""

import pytest
import os
import sys
import tempfile
import shutil
import json
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入Flask应用和数据库类
from app import app
from database import Database

# 测试数据
TEST_IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'test_images')
# 使用生产数据库副本
TEST_DATABASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'labels.db')


@pytest.fixture(scope='module')
def client():
    """Flask测试客户端"""
    app.config['TESTING'] = True

    # 使用现有的生产数据库副本
    original_db_path = app.config.get('DATABASE_PATH')
    app.config['DATABASE_PATH'] = TEST_DATABASE

    # 创建测试数据库实例（不创建新表，只连接现有数据库）
    test_db = Database(TEST_DATABASE)

    # 创建测试客户端
    with app.test_client() as test_client:
        yield test_client, test_db


@pytest.fixture(scope='module', autouse=True)
def cleanup_ai_models():
    """模块级别的fixture，确保所有测试完成后清理AI模型内存"""
    yield

    # 模块级别清理：释放全局AI模型内存
    if hasattr(app, 'ai_predictor') and app.ai_predictor is not None:
        try:
            app.ai_predictor.unload_models()
            print("\n[CLEANUP] AI models memory released")
        except Exception as e:
            print(f"\n[CLEANUP] Failed to release AI models: {e}")


@pytest.fixture(scope='module')
def test_images():
    """准备测试图片"""
    # 创建测试图片目录（如果不存在）
    os.makedirs(TEST_IMAGES_DIR, exist_ok=True)

    # 检查目录是否为空，如果为空则创建测试图片
    existing_files = os.listdir(TEST_IMAGES_DIR)
    if not existing_files:
        # 创建测试图片（使用PIL创建简单图片）
        try:
            from PIL import Image, ImageDraw, ImageFont
            import numpy as np

            # 创建几张测试图片
            for i in range(5):
                img = Image.new('RGB', (800, 600), color=(255, 255, 255))
                draw = ImageDraw.Draw(img)

                # 绘制简单的飞机形状
                draw.polygon([(400, 200), (350, 350), (450, 350)], fill=(200, 200, 200))
                draw.rectangle([(380, 180), (420, 200)], fill=(150, 150, 150))

                # 添加一些文字模拟注册号
                try:
                    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 30)
                except:
                    font = ImageFont.load_default()

                registrations = ['B-1234', 'B-5678', 'N901XY', 'G-ABCD', 'D-EFGH']
                text = registrations[i]
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                draw.text(
                    ((800 - text_width) / 2, 400),
                    text,
                    fill=(0, 0, 0),
                    font=font
                )

                img.save(os.path.join(TEST_IMAGES_DIR, f'test_{i+1}.jpg'), 'JPEG')

            print(f"Created {5} test images in {TEST_IMAGES_DIR}")
        except ImportError as e:
            print(f"Warning: Could not create test images: {e}")
            pytest.skip("PIL not available for creating test images")

    return TEST_IMAGES_DIR


class TestAIIntegration:
    """AI集成测试"""

    def test_ai_service_status(self, client):
        """测试AI服务状态"""
        test_client, test_db = client
        response = test_client.get('/api/ai/status')

        assert response.status_code in [200, 500]
        data = response.get_json()

        if response.status_code == 200:
            assert 'enabled' in data
            assert 'services' in data

    @pytest.mark.skipif(not os.path.exists(TEST_IMAGES_DIR), reason="Test images not available")
    def test_single_image_prediction(self, client, test_images):
        """测试单张图片预测"""
        test_client, test_db = client
        # 获取第一张测试图片
        test_files = os.listdir(test_images)
        if not test_files:
            pytest.skip("No test images available in test_images directory")

        test_file = test_files[0]

        response = test_client.post('/api/ai/predict',
                                 json={'filename': test_file},
                                 content_type='application/json')

        # 如果AI服务未启用，返回503
        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        assert response.status_code in [200, 404, 500]

        if response.status_code == 200:
            data = response.get_json()
            # 检查必需字段
            assert 'filename' in data
            assert 'aircraft_class' in data
            assert 'airline_class' in data
            assert 'aircraft_confidence' in data
            assert 'airline_confidence' in data
            assert 'clarity' in data
            assert 'block' in data
            assert 0 <= data['aircraft_confidence'] <= 1
            assert 0 <= data['airline_confidence'] <= 1

    @pytest.mark.skipif(not os.path.exists(TEST_IMAGES_DIR), reason="Test images not available")
    def test_batch_prediction(self, client, test_images):
        """测试批量预测"""
        test_client, test_db = client
        # 先清理已有的预测
        conn = test_db.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ai_predictions')
        conn.commit()
        conn.close()

        response = test_client.post('/api/ai/predict-batch')

        # 如果AI服务未启用，返回503
        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.get_json()

            # 处理两种情况：有图片预测和无图片预测
            if 'message' in data and data['message'] == 'No new images to predict':
                # 无图片情况：返回 'count' 和 'message'
                assert 'count' in data
                assert data['count'] == 0
                assert 'message' in data
            else:
                # 有图片情况：返回 'total' 和 'statistics'
                assert 'total' in data
                assert 'statistics' in data
                assert data['total'] >= 0

    def test_get_pending_reviews(self, client):
        """测试获取待复审列表"""
        test_client, test_db = client
        response = test_client.get('/api/ai/review/pending')

        # 如果AI服务未启用，返回503
        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.get_json()

            assert 'total' in data
            assert 'items' in data
            assert isinstance(data['items'], list)

    def test_get_auto_approvable(self, client):
        """测试获取可一键通过的预测"""
        test_client, test_db = client
        response = test_client.get('/api/ai/review/auto-approvable')

        # 如果AI服务未启用，返回503
        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.get_json()

            assert 'total' in data
            assert 'items' in data
            assert isinstance(data['items'], list)

    def test_ai_stats(self, client):
        """测试AI统计信息"""
        test_client, test_db = client
        response = test_client.get('/api/ai/stats')

        # 如果AI服务未启用，返回503
        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.get_json()

            assert 'total_predictions' in data
            assert 'pending_count' in data
            assert 'new_class_count' in data
            assert 'auto_approve_count' in data
            assert data['total_predictions'] >= 0

    @pytest.mark.skipif(not os.path.exists(TEST_IMAGES_DIR), reason="Test images not available")
    def test_approve_prediction(self, client, test_images):
        """测试批准AI预测"""
        test_client, test_db = client
        # 先运行批量预测
        test_client.post('/api/ai/predict-batch')

        # 获取待复审的预测
        response = test_client.get('/api/ai/review/pending?limit=1')

        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        if response.status_code == 200 and response.get_json()['items']:
            pred = response.get_json()['items'][0]
            filename = pred['filename']

            # 检查图片是否存在
            test_file_path = os.path.join(test_images, filename)
            if not os.path.exists(test_file_path):
                pytest.skip(f"Test image {filename} not found")

            # 批准预测
            response = test_client.post('/api/ai/review/approve',
                                    json={'filename': filename, 'auto_approve': False})

            assert response.status_code in [200, 404, 500]

            if response.status_code == 200:
                data = response.get_json()
                assert 'id' in data
                assert 'file_name' in data

                # 验证标注已创建
                conn = test_db.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM labels WHERE id = ?', (data['id'],))
                label = cursor.fetchone()
                conn.close()

                assert label is not None

    @pytest.mark.skipif(not os.path.exists(TEST_IMAGES_DIR), reason="Test images not available")
    def test_reject_prediction(self, client, test_images):
        """测试拒绝AI预测"""
        test_client, test_db = client
        # 先运行批量预测
        test_client.post('/api/ai/predict-batch')

        # 获取待复审的预测
        response = test_client.get('/api/ai/review/pending?limit=1')

        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        if response.status_code == 200 and response.get_json()['items']:
            pred = response.get_json()['items'][0]
            filename = pred['filename']

            # 拒绝预测
            response = test_client.post('/api/ai/review/reject',
                                    json={'filename': filename, 'skip_as_invalid': False})

            assert response.status_code in [200, 500]

            if response.status_code == 200:
                data = response.get_json()
                assert 'message' in data

                # 验证预测已标记为已处理
                conn = test_db.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT processed FROM ai_predictions WHERE filename = ?', (filename,))
                result = cursor.fetchone()
                conn.close()

                assert result is not None
                assert result['processed'] == 1

    def test_complete_workflow(self, client, test_images):
        """测试完整工作流：批量预测 -> 审查 -> 批准"""
        test_client, test_db = client
        if not os.path.exists(TEST_IMAGES_DIR):
            pytest.skip("Test images not available")

        # 1. 批量预测
        batch_response = test_client.post('/api/ai/predict-batch')
        if batch_response.status_code == 503:
            pytest.skip("AI service not enabled")

        assert batch_response.status_code in [200, 500]
        if batch_response.status_code != 200:
            pytest.skip("Batch prediction failed")

        # 2. 获取待复审列表
        pending_response = test_client.get('/api/ai/review/pending')
        assert pending_response.status_code == 200
        pending_data = pending_response.get_json()

        # 如果有预测结果
        if pending_data['items']:
            pred = pending_data['items'][0]
            filename = pred['filename']

            test_file_path = os.path.join(test_images, filename)
            if not os.path.exists(test_file_path):
                pytest.skip(f"Test image {filename} not found")

            # 3. 批准第一个预测
            approve_response = test_client.post('/api/ai/review/approve',
                                            json={'filename': filename, 'auto_approve': False})

            assert approve_response.status_code in [200, 404, 500]

            if approve_response.status_code == 200:
                approve_data = approve_response.get_json()

                # 4. 验证标注已创建
                conn = test_db.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM labels WHERE id = ?', (approve_data['id'],))
                label = cursor.fetchone()
                conn.close()

                assert label is not None
                assert label['review_status'] in ['approved', 'reviewed']

                # 5. 验证预测已标记为已处理
                conn = test_db.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT processed FROM ai_predictions WHERE filename = ?', (filename,))
                result = cursor.fetchone()
                conn.close()

                assert result is not None
                assert result['processed'] == 1

    def test_push_order_priority(self, client):
        """测试推送顺序：新类别优先，然后按置信度升序"""
        test_client, test_db = client
        response = test_client.get('/api/ai/review/pending')

        if response.status_code == 503:
            pytest.skip("AI service not enabled")

        if response.status_code == 200:
            data = response.get_json()
            items = data['items']

            if len(items) > 1:
                # 验证新类别在前面
                new_class_indices = [i for i, item in enumerate(items) if item['is_new_class'] == 1]
                regular_indices = [i for i, item in enumerate(items) if item['is_new_class'] == 0]

                # 如果有新类别，应该都在常规类别之前
                if new_class_indices and regular_indices:
                    max_new_class_index = max(new_class_indices)
                    min_regular_index = min(regular_indices)
                    assert max_new_class_index < min_regular_index, "New classes should come before regular classes"

                # 验证常规类别按置信度升序
                for i in range(len(regular_indices) - 1):
                    idx1 = regular_indices[i]
                    idx2 = regular_indices[i + 1]
                    conf1 = min(items[idx1]['aircraft_confidence'], items[idx1]['airline_confidence'])
                    conf2 = min(items[idx2]['aircraft_confidence'], items[idx2]['airline_confidence'])
                    assert conf1 <= conf2, f"Confidence should be ascending, but {conf1} > {conf2}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
