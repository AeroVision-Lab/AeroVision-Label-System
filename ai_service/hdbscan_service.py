"""
HDBSCAN新类别检测服务
使用HDBSCAN聚类识别新类别
"""

import logging
from typing import Dict, Any, List, Optional
import numpy as np

# 检查hdbscan是否可用
HDBSCAN_AVAILABLE = False
try:
    import hdbscan
    HDBSCAN_AVAILABLE = True
except ImportError:
    logging.warning("hdbscan not found. New class detection will be disabled.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HDBSCANNewClassDetector:
    """HDBSCAN新类别检测器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化新类别检测器

        Args:
            config: HDBSCAN配置
        """
        self.enabled = config.get('enabled', True) and HDBSCAN_AVAILABLE
        self.min_cluster_size = config.get('min_cluster_size', 5)
        self.min_samples = config.get('min_samples', 3)
        self.metric = config.get('metric', 'euclidean')
        self.cluster_selection_method = config.get('cluster_selection_method', 'eom')
        self.prediction_data = config.get('prediction_data', True)

        self._clusterer = None
        self._labels: Optional[np.ndarray] = None
        self._outlier_scores: Optional[np.ndarray] = None

        if self.enabled:
            logger.info(f"HDBSCANNewClassDetector initialized")
        else:
            logger.info("HDBSCANNewClassDetector disabled")

    def detect_new_classes(
        self,
        predictions: List[Dict[str, Any]],
        embeddings: Optional[np.ndarray] = None
    ) -> List[int]:
        """
        检测新类别

        Args:
            predictions: 预测结果列表
            embeddings: 特征嵌入（可选，如果为None则使用预测置信度）

        Returns:
            新类别的索引列表
        """
        if not self.enabled:
            return []

        if len(predictions) == 0:
            return []

        logger.info(f"Detecting new classes from {len(predictions)} predictions...")

        # 使用置信度作为嵌入（如果未提供）
        if embeddings is None:
            embeddings = self._extract_confidence_features(predictions)

        # 聚类
        self._cluster_embeddings(embeddings)

        # 获取异常点索引
        outlier_indices = np.where(self._labels == -1)[0]

        logger.info(
            f"Found {len(outlier_indices)} potential new class samples "
            f"({len(outlier_indices)/len(predictions)*100:.1f}%)"
        )

        return outlier_indices.tolist()

    def _extract_confidence_features(self, predictions: List[Dict[str, Any]]) -> np.ndarray:
        """
        从预测结果中提取置信度特征

        Args:
            predictions: 预测结果列表

        Returns:
            特征矩阵
        """
        features = []
        for pred in predictions:
            aircraft_conf = pred['aircraft']['confidence']
            airline_conf = pred['airline']['confidence']
            # 使用最小置信度作为特征
            features.append([min(aircraft_conf, airline_conf)])

        return np.array(features)

    def _cluster_embeddings(self, embeddings: np.ndarray):
        """使用HDBSCAN聚类嵌入"""
        logger.info(f"Clustering {len(embeddings)} samples...")

        self._clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric=self.metric,
            cluster_selection_method=self.cluster_selection_method,
            prediction_data=self.prediction_data
        )

        self._clusterer.fit(embeddings)

        self._labels = self._clusterer.labels_

        # 计算异常分数
        if self.prediction_data:
            self._outlier_scores = self._clusterer.outlier_scores_
        else:
            # 如果没有prediction_data，使用简单的距离计算
            self._outlier_scores = np.zeros(len(embeddings))

        n_clusters = len(set(self._labels)) - (1 if -1 in self._labels else 0)
        n_noise = list(self._labels).count(-1)

        logger.info(f"Clustering complete: {n_clusters} clusters, {n_noise} noise points")

    def get_outlier_scores(self) -> np.ndarray:
        """获取异常分数"""
        if self._outlier_scores is None:
            raise RuntimeError("No clustering results available")
        return self._outlier_scores

    def get_statistics(self, predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """获取统计信息"""
        if not self.enabled or self._labels is None:
            return {
                "total_samples": len(predictions),
                "n_clusters": 1,
                "n_noise": 0,
                "noise_ratio": 0.0,
                "mean_outlier_score": 0.0,
                "available": False
            }

        n_clusters = len(set(self._labels)) - (1 if -1 in self._labels else 0)
        n_noise = list(self._labels).count(-1)
        n_total = len(self._labels)

        return {
            "total_samples": n_total,
            "n_clusters": n_clusters,
            "n_noise": n_noise,
            "noise_ratio": n_noise / n_total if n_total > 0 else 0.0,
            "mean_outlier_score": float(np.mean(self._outlier_scores)),
            "available": True
        }

    def cleanup(self):
        """清理HDBSCAN资源"""
        if self._clusterer is not None:
            del self._clusterer
            self._clusterer = None

        self._labels = None
        self._outlier_scores = None
        logger.info("HDBSCANNewClassDetector resources cleaned up")

    def __del__(self):
        """析构时自动清理"""
        self.cleanup()
